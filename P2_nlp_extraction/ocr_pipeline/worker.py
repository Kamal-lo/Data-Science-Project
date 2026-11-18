"""Worker isolé : détection unique, double reconnaissance, exports progressifs."""
import argparse
import json
from pathlib import Path
from time import perf_counter

from .layout import detections, reading_order
from .routing import RULES, route
from .spacing import propose, segments
from ..scripts.ocr_common import local_path, write_json


def error(stage, exc):
    return {'stage': stage, 'type': type(exc).__name__, 'message': str(exc)}


def page_file(folder, number):
    return folder/'pages'/f'page_{number:03d}.json'


def process_document(request, backend_factory=None):
    """Backend injectable pour tests techniques sans exécuter de modèles."""
    import numpy as np
    import pymupdf
    from PIL import Image, ImageOps
    from .models import LocalModels
    folder = local_path(request['run_dir'])
    backend_factory = backend_factory or LocalModels
    backend = None

    def progress(phase, page=None):
        write_json(folder/'progress.json', {'phase': phase, 'page': page})

    with pymupdf.open(request['pdf_path']) as document:
        for number in request['pages']:
            print(f'Page {number}: rendu et détection automatique.', flush=True)
            progress('page', number)
            start_page = perf_counter()
            record = {'page': number, 'status': 'processing', 'blocks': [], 'errors': [], 'warnings': [],
                      'detected_block_count': 0, 'raw_detection_count': 0, 'timings': {}}
            write_json(page_file(folder, number), record)
            try:
                page = document[number-1]
                scale = request['dpi']/72
                if (page.rect.width*scale+1)*(page.rect.height*scale+1) > request['max_pixels']:
                    raise ValueError('Page trop grande pour la limite max_pixels.')
                start = perf_counter()
                pixmap = page.get_pixmap(dpi=request['dpi'], colorspace=pymupdf.csRGB, alpha=False)
                rgb = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, 3).copy()
                width, height = pixmap.width, pixmap.height
                source = folder/'images'/f'page_{number:03d}.png'
                source.parent.mkdir(parents=True, exist_ok=True)
                pixmap.save(source)
                record.update(image=str(source), image_size=[width, height], dpi=request['dpi'],
                              pdf_rect=list(page.rect), native_characters=len(page.get_text()),
                              native_layer_policy='render_once_no_native_text_merge')
                record['timings']['render_seconds'] = perf_counter()-start
                if int(rgb.min()) >= 245:
                    record.update(status='near_blank', warnings=[{'code': 'near_blank_pixel_heuristic_unverified'}])
                    continue
                if backend is None:
                    progress('initializing', number)
                    backend = backend_factory(cpu_threads=request['cpu_threads'])
                    write_json(folder/'models.json', dict(backend.metadata,
                                                         initialization_seconds=backend.initialization_seconds))
                    progress('page', number)
                bgr = rgb[:, :, ::-1].copy()
                start = perf_counter()
                polygons, scores = backend.detect(bgr)
                record['timings']['detection_seconds'] = perf_counter()-start
                kept, duplicates, overlaps = detections(polygons, scores, width, height)
                record.update(raw_detection_count=len(polygons), detected_block_count=len(kept),
                              duplicate_detections=duplicates, detection_overlap_conflicts=overlaps)
                print(f'Page {number}: {len(polygons)} détections, {len(kept)} blocs après déduplication.', flush=True)
                if overlaps:
                    record['warnings'].append({'code': 'overlapping_detections', 'pairs': overlaps})
                write_json(folder/'pages'/f'page_{number:03d}_detections.json',
                           {'detections': kept, 'duplicates': duplicates, 'conflicts': overlaps})
                record['timings'].update(recognition_fr_seconds=0, recognition_ar_seconds=0,
                                          spacing_seconds=0, routing_seconds=0)
                for detection in kept:
                    block_id = f'p{number:03d}_b{detection["detection_index"]:04d}'
                    crop, candidates = None, {}
                    try:
                        crop = backend.crop(bgr, detection['polygon'])
                    except Exception as exc:
                        record['errors'].append(dict(error('crop', exc), block_id=block_id))
                    for language in ('fr', 'ar'):
                        start = perf_counter()
                        try:
                            if crop is None:
                                raise ValueError('Recadrage du bloc indisponible.')
                            candidates[language] = backend.recognize(crop, language)
                        except Exception as exc:
                            candidates[language] = {'text': '', 'confidence': 0, 'error': str(exc)}
                            record['errors'].append(dict(error('recognition_'+language, exc), block_id=block_id))
                        record['timings']['recognition_'+language+'_seconds'] += perf_counter()-start
                    start = perf_counter()
                    block = dict(detection, block_id=block_id, page=number, **route(candidates))
                    record['timings']['routing_seconds'] += perf_counter()-start
                    box = block['bbox']
                    rect = page.rect
                    block['bbox_pdf_points'] = [rect.x0+box[0]/width*rect.width, rect.y0+box[1]/height*rect.height,
                                                rect.x0+box[2]/width*rect.width, rect.y0+box[3]/height*rect.height]
                    block['pdf_coordinates'] = 'rotated_rendered_page_rect_top_left_origin_points'
                    block['arabic_spacing_proposal'] = None
                    if block['language'] == 'ar' and request['arabic_spacing'] == 'suggest' and crop is not None:
                        start = perf_counter()
                        try:
                            pil = Image.fromarray(crop[:, :, ::-1])
                            analysis = segments(pil)
                            words = []
                            # Limiter le coût ; une segmentation trop fragmentée provoque une abstention.
                            if len(analysis['segments']) > 32:
                                analysis.update(status='abstain_too_many_segments', segments=[])
                            for segment in analysis['segments']:
                                img = ImageOps.expand(pil.crop((segment['x0'], 0, segment['x1'], pil.height)),
                                                      border=12, fill='white')
                                word = backend.recognize(np.asarray(img)[:, :, ::-1].copy(), 'ar')
                                words.append(dict(word, bbox_crop=[segment['x0'], 0, segment['x1'], pil.height],
                                                  coordinate_system='rectified_block_crop_pixels_before_padding', padding=12))
                            block['arabic_spacing_proposal'] = dict(propose(block['raw_text'], [w['text'] for w in words]),
                                                                    segmentation=analysis, words=words,
                                                                    raw_text_unchanged=True)
                        except Exception as exc:
                            block['warnings'].append('spacing_failed')
                            block['needs_review'] = True
                            record['errors'].append(dict(error('spacing', exc), block_id=block_id))
                        record['timings']['spacing_seconds'] += perf_counter()-start
                    record['blocks'].append(block)
                    print(f'{block_id}: {block["language"]}, {block["routing_reason"]}, '
                          f'fr={candidates["fr"]["confidence"]:.3f}, ar={candidates["ar"]["confidence"]:.3f}', flush=True)
                    write_json(page_file(folder, number), record)
                record['blocks'], ordering_warnings = reading_order(record['blocks'])
                record['warnings'].extend(ordering_warnings)
                record['status'] = ('no_text_detected' if not kept else 'needs_review'
                                    if record['errors'] or overlaps or any(b['needs_review'] for b in record['blocks'])
                                    or ordering_warnings else 'ok')
                if not kept:
                    record['warnings'].append({'code': 'absence_of_detection_is_not_proof_of_empty_page'})
            except Exception as exc:
                record['status'] = 'error'
                record['errors'].append(error('page', exc))
                if backend is None and 'image' in record and record.get('status') != 'near_blank':
                    write_json(folder/'fatal_error.json', error('initialization_or_first_page', exc))
            finally:
                record['timings']['page_total_seconds'] = perf_counter()-start_page
                write_json(page_file(folder, number), record)
            if (folder/'fatal_error.json').exists() or (record['errors'] and request['on_error'] == 'raise'):
                break
    progress('finished')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', required=True, type=Path)
    args = parser.parse_args()
    request = json.loads(local_path(args.request).read_text(encoding='utf-8'))
    try:
        process_document(request)
    except Exception as exc:
        write_json(local_path(request['run_dir'])/'fatal_error.json', error('worker', exc))
        raise


if __name__ == '__main__':
    main()

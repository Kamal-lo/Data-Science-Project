"""Worker isolé : détection unique, double reconnaissance, exports progressifs."""
import argparse
import json
import os
import sys
from pathlib import Path
from time import perf_counter, monotonic, sleep

from .layout import detections, reading_order
from .spacing import propose, segments
from .preprocessing import enhance_scan
from .quality import page_summary
from .recovery import FallbackBudget, detect_page, recognize_block
from .resources import memory_sample
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

    def atomic_json(path, value):
        temporary = path.with_suffix('.tmp')
        write_json(temporary, value)
        # Windows readers may briefly hold a handle without FILE_SHARE_DELETE.
        for attempt in range(101):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 100: raise
                sleep(.005)

    def progress(phase, page=None, **details):
        atomic_json(folder/'progress.json', dict(phase=phase, page=page, **details))

    with pymupdf.open(request['pdf_path']) as document:
        for number in request['pages']:
            print(f'Page {number}: rendu et détection automatique.', flush=True)
            progress('page', number)
            start_page = perf_counter()
            record = {'page': number, 'status': 'processing', 'blocks': [], 'errors': [], 'warnings': [],
                      'detected_block_count': 0, 'raw_detection_count': 0, 'timings': {}, 'memory_events': []}

            def model_event(stage, details=None):
                sample = memory_sample(stage, **(details or {}))
                record['memory_events'].append(sample)
                # Durable before entering native initialization/detection. This
                # also preserves page geometry when the native runtime aborts.
                atomic_json(page_file(folder, number), record)
                if backend is not None:
                    atomic_json(folder/'models.json', dict(backend.metadata,
                                                          initialization_seconds=backend.initialization_seconds))

            def observe(event, kind, remaining, primary):
                if event == 'finish':
                    pending = record.get('fallback_in_progress', {})
                    if pending and monotonic() >= pending['deadline_monotonic']:
                        record['fallback_interruption'] = dict(pending, interruption='fallback_timeout',
                                                               outcome='late_result_not_selected')
                        for saved in record['blocks']:
                            if saved['block_id'] == pending.get('block_id'):
                                saved['fallback_attempted'] = True
                                saved['fallback_skipped_reason'] = 'fallback_timeout'
                                saved['warnings'].append('fallback_timeout_late_result_not_selected')
                        raise TimeoutError('fallback_timeout: result returned after its deadline.')
                    record.pop('fallback_in_progress', None)
                    progress('page', number)
                    return
                deadline = monotonic() + remaining
                record['fallback_in_progress'] = {'kind': kind, 'deadline_monotonic': deadline,
                                                   'remaining_seconds': remaining}
                if kind == 'block':
                    # Save the primary before entering any potentially blocking native call.
                    checkpoint = make_block(primary)
                    checkpoint['warnings'].append('fallback_pending_primary_checkpoint')
                    record['blocks'].append(checkpoint)
                    record['fallback_in_progress']['block_id'] = block_id
                elif kind == 'detection':
                    record['detection_attempts'] = primary
                record['fallback'] = recovery.report()
                atomic_json(page_file(folder, number), record)
                progress('fallback', number, fallback_deadline=deadline, fallback_kind=kind)

            recovery = FallbackBudget(request.get('fallback_mode', 'off'), request.get('max_fallback_blocks', 8),
                                      request.get('fallback_timeout_seconds', 20), observer=observe)

            def make_block(recognized):
                block = dict(detection, block_id=block_id, page=number, **recognized)
                box, rect = block['bbox'], page.rect
                block['bbox_pdf_points'] = [rect.x0+box[0]/width*rect.width, rect.y0+box[1]/height*rect.height,
                                            rect.x0+box[2]/width*rect.width, rect.y0+box[3]/height*rect.height]
                block['pdf_coordinates'] = 'rotated_rendered_page_rect_top_left_origin_points'
                block['arabic_spacing_proposal'] = None
                return block
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
                bgr = rgb[:, :, ::-1].copy()
                image_variant = 'original'
                record['preprocessing'] = {'primary_variant': image_variant, 'geometry_changed': False,
                                           'coordinate_transform': 'identity', 'original_image': str(source)}
                model_event('page_rendered', {'image_shape': [height, width, 3]})
                near_blank = int(rgb.min()) >= 245
                faint = near_blank and recovery.mode != 'off' and float(rgb[::16, ::16].std()) > .25
                if near_blank and not faint:
                    record.update(status='near_blank', warnings=[{'code': 'near_blank_pixel_heuristic_unverified'}])
                    continue
                if faint and recovery.reserve('page') is None:
                    start = perf_counter()
                    recovery.begin('faint_preprocessing')
                    try:
                        bgr, metadata = enhance_scan(bgr, request['max_pixels'])
                    finally:
                        recovery.spent_seconds += perf_counter() - start
                        recovery.finish('faint_preprocessing')
                    image_variant = 'contrast_for_faint_scan'
                    record['preprocessing'].update(primary_variant=image_variant, parameters=metadata)
                    record['warnings'].append({'code': 'faint_scan_contrast_unvalidated'})
                if backend is None:
                    progress('initializing', number)
                    if backend_factory is LocalModels:
                        backend = backend_factory(cpu_threads=request['cpu_threads'], observer=model_event,
                            **({'detector_max_side': request['detector_max_side']} if request.get('detector_max_side') is not None else {}))
                    else:
                        backend = backend_factory(cpu_threads=request['cpu_threads'])
                    write_json(folder/'models.json', dict(backend.metadata,
                                                         initialization_seconds=backend.initialization_seconds))
                    progress('page', number)
                start = perf_counter()
                model_event('primary_detection_before')
                polygons, scores, bgr, detection_history = detect_page(backend, bgr, recovery, request['max_pixels'],
                                                                      image_variant=image_variant)
                model_event('primary_detection_after')
                record['detection_attempts'] = detection_history
                if detection_history['selected_error']:
                    raise RuntimeError(detection_history['selected_error']['message'])
                if detection_history['selected_attempt']:
                    image_variant = 'contrast_grayscale'
                    record['preprocessing'].update(selected_variant=image_variant,
                                                    parameters=detection_history['selected_preprocessing'])
                    record['warnings'].append({'code': 'preprocessed_detection_fallback_selected'})
                if image_variant != 'original':
                    processed_path = folder/'images'/f'page_{number:03d}_preprocessed.png'
                    Image.fromarray(bgr[:, :, ::-1]).save(processed_path)
                    record['preprocessing']['selected_image'] = str(processed_path)
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
                    recognized, recognition_errors, recognition_times = recognize_block(
                        backend, crop, recovery, request['max_pixels'], image_variant=image_variant)
                    # Replace the temporary primary checkpoint only after the attempt returns.
                    if record['blocks'] and record['blocks'][-1]['block_id'] == block_id:
                        record['blocks'].pop()
                    record['errors'].extend(dict(issue, block_id=block_id) for issue in recognition_errors)
                    for key, value in recognition_times.items(): record['timings'][key] += value
                    candidates = recognized['recognition_candidates']
                    block = make_block(recognized)
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
                    atomic_json(page_file(folder, number), record)
                record['blocks'], ordering_warnings = reading_order(record['blocks'])
                record['warnings'].extend(ordering_warnings)
                record['status'] = ('no_text_detected' if not kept else 'needs_review'
                                    if record['errors'] or overlaps or any(b['needs_review'] for b in record['blocks'])
                                    or ordering_warnings or image_variant != 'original' else 'ok')
                if not kept:
                    record['warnings'].append({'code': 'absence_of_detection_is_not_proof_of_empty_page'})
            except Exception as exc:
                record['status'] = ('needs_review' if record['blocks'] and record.get('fallback_interruption') else 'error')
                record['errors'].append(error('page', exc))
                if backend is None and 'image' in record and record.get('status') != 'near_blank':
                    write_json(folder/'fatal_error.json', error('initialization_or_first_page', exc))
            finally:
                record['fallback'] = recovery.report()
                record['quality_summary'] = page_summary(record['blocks'])
                record['timings']['fallback_seconds'] = recovery.spent_seconds
                record['timings']['page_total_seconds'] = perf_counter()-start_page
                atomic_json(page_file(folder, number), record)
            if (folder/'fatal_error.json').exists() or (record['errors'] and request['on_error'] == 'raise'):
                break
    progress('finished')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', required=True, type=Path)
    args = parser.parse_args()
    request = json.loads(local_path(args.request).read_text(encoding='utf-8'))
    try:
        from .resources import container_memory_limit, join_job
        if sys.platform == 'linux':
            container_memory_limit()
            if os.getpid() != os.getpgrp():
                raise RuntimeError('Isolated Linux OCR process group required.')
            mechanism = 'linux_cgroup_v2_and_process_group'
        else:
            join_job(request['resource_job_name'])
            mechanism = 'windows_job_object'
        write_json(local_path(request['run_dir'])/'resource_guard.json',
                   {'memory_guard_installed': True, 'mechanism': mechanism})
        process_document(request)
    except Exception as exc:
        write_json(local_path(request['run_dir'])/'fatal_error.json', error('worker', exc))
        raise


if __name__ == '__main__':
    main()

"""Adaptation isolée des interfaces PaddleX 3.3.13 installées, modèles locaux seulement."""
import importlib.metadata
import json
import os
from pathlib import PurePosixPath
from time import perf_counter

from ..scripts.ocr_common import ROOT, configure_cache, sha256

MODEL_NAMES = {'det': 'PP-OCRv5_mobile_det', 'fr': 'latin_PP-OCRv5_mobile_rec',
               'ar': 'arabic_PP-OCRv3_mobile_rec'}
DETECTION_SETTINGS = {'limit_side_len': 64, 'limit_type': 'min', 'max_side_limit': 4000,
                      'thresh': .3, 'box_thresh': .6, 'unclip_ratio': 1.5}


def preflight():
    expected = {'paddlepaddle': '3.2.2', 'paddleocr': '3.3.2', 'paddlex': '3.3.13'}
    versions = {name: importlib.metadata.version(name) for name in expected}
    if versions != expected:
        raise RuntimeError(f'Adaptateur testé uniquement avec {expected}, versions présentes : {versions}')
    inventory = json.loads((ROOT/'config/model_inventory.json').read_text(encoding='utf-8'))
    paths, hashes = {}, []
    for key, name in MODEL_NAMES.items():
        folder = ROOT/'.cache/paddlex/official_models'/name
        for filename in ('inference.json', 'inference.yml', 'inference.pdiparams'):
            path = folder/filename
            if not path.is_file():
                raise FileNotFoundError(f'Modèle local absent : {path}. Téléchargement interdit.')
            entry = next((item for item in inventory
                          if PurePosixPath(item['path']).name == filename
                          and name in PurePosixPath(item['path']).parts), None)
            digest = sha256(path)
            if not entry or digest != entry['sha256']:
                raise ValueError(f'Empreinte de modèle non conforme : {path}')
            hashes.append({'path': path.relative_to(ROOT).as_posix(), 'sha256': digest})
        paths[key] = str(folder)
    return {'versions': versions, 'paths': paths, 'models': hashes, 'downloads': False}


class LocalModels:
    def __init__(self, cpu_threads=4):
        start = perf_counter()
        self.metadata = preflight()
        configure_cache()
        os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'
        os.environ['HF_HUB_OFFLINE'] = '1'
        from paddlex.inference import create_predictor, PaddlePredictorOption
        from paddlex.inference.pipelines.components import CropByPolys
        options = PaddlePredictorOption(run_mode='paddle', device_type='cpu', cpu_threads=cpu_threads)
        self.models = {}
        for key in ('det', 'fr', 'ar'):
            # Identique au pipeline OCR installé déjà utilisé par PaddleEngine.
            # Réduire toute la page à 960 px mélangeait/dégradait certaines lignes.
            settings = DETECTION_SETTINGS if key == 'det' else {}
            self.models[key] = create_predictor(model_name=MODEL_NAMES[key], model_dir=self.metadata['paths'][key],
                                                device='cpu', pp_option=options.copy(), batch_size=1, **settings)
        self.cropper = CropByPolys(det_box_type='quad')
        self.initialization_seconds = perf_counter()-start
        self.metadata['parameters'] = {'device': 'cpu', 'cpu_threads': cpu_threads, 'mkldnn': False,
                                       'detector': MODEL_NAMES['det'], 'detection': DETECTION_SETTINGS,
                                       'orientation_unwarping': False}

    def detect(self, bgr_image):
        result = next(iter(self.models['det'](bgr_image)))
        return result['dt_polys'], result.get('dt_scores', [])

    def crop(self, bgr_image, polygon):
        import numpy as np
        return next(iter(self.cropper(bgr_image, np.asarray([polygon], dtype='float32'))))

    def recognize(self, image, language):
        result = next(iter(self.models[language](image)))
        return {'text': str(result['rec_text']), 'confidence': float(result['rec_score']),
                'model': MODEL_NAMES[language]}

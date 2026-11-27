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


def _predictor_components():
    from paddlex.inference import create_predictor, PaddlePredictorOption
    from paddlex.inference.pipelines.components import CropByPolys
    return create_predictor, PaddlePredictorOption, CropByPolys


class LocalModels:
    def __init__(self, cpu_threads=4, observer=None, detector_max_side=None):
        start = perf_counter()
        self.metadata = preflight()
        configure_cache()
        os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'
        os.environ['HF_HUB_OFFLINE'] = '1'
        self._factory, option_type, cropper_type = _predictor_components()
        self._options = option_type(run_mode='paddle', device_type='cpu', cpu_threads=cpu_threads)
        self._observer = observer
        self.models = {}
        self._load_errors = {}
        self.metadata['model_load_counts'] = {key: 0 for key in MODEL_NAMES}
        self.metadata['model_load_events'] = []
        self.detection_settings = dict(DETECTION_SETTINGS)
        if detector_max_side is not None:
            if type(detector_max_side) is not int or not 32 <= detector_max_side <= 4000:
                raise ValueError("detector_max_side invalide")
            self.detection_settings.update(limit_side_len=detector_max_side, limit_type="max", max_side_limit=detector_max_side)
        self._load('det')
        self.cropper = cropper_type(det_box_type='quad')
        self.initialization_seconds = perf_counter()-start
        self.metadata['parameters'] = {'device': 'cpu', 'cpu_threads': cpu_threads, 'mkldnn': False,
                                       'detector': MODEL_NAMES['det'], 'detection': dict(self.detection_settings),
                                       'orientation_unwarping': False, 'recognizer_loading': 'lazy_once',
                                       'initialization_scope': 'detector_only_recognizer_loading_timed_in_recognition'}

    def _emit(self, stage, **details):
        if self._observer:
            self._observer(stage, dict(details, loaded_models=list(self.models),
                                      model_load_counts=dict(self.metadata['model_load_counts'])))

    def _load(self, key):
        if key not in MODEL_NAMES:
            raise ValueError('Unsupported local OCR model key.')
        if key in self.models:
            return self.models[key]
        if key in self._load_errors:
            raise RuntimeError(f'Previous model loading failure: {key}') from self._load_errors[key]
        started = perf_counter()
        self.metadata['model_load_counts'][key] += 1
        self._emit('model_load_before', model_key=key)
        try:
            settings = self.detection_settings if key == 'det' else {}
            self.models[key] = self._factory(model_name=MODEL_NAMES[key], model_dir=self.metadata['paths'][key],
                                            device='cpu', pp_option=self._options.copy(), batch_size=1, **settings)
        except Exception as exc:
            self._load_errors[key] = exc
            self.metadata['model_load_events'].append({'model_key': key, 'status': 'error',
                'type': type(exc).__name__, 'message': str(exc), 'seconds': perf_counter()-started})
            self._emit('model_load_error', model_key=key, error_type=type(exc).__name__)
            raise
        self.metadata['model_load_events'].append({'model_key': key, 'status': 'loaded',
                                                   'seconds': perf_counter()-started})
        self._emit('model_load_after', model_key=key)
        return self.models[key]

    def detect(self, bgr_image):
        self._emit('detection_before', image_shape=list(bgr_image.shape))
        result = next(iter(self.models['det'](bgr_image)))
        self._emit('detection_after', detection_count=len(result['dt_polys']))
        return result['dt_polys'], result.get('dt_scores', [])

    def crop(self, bgr_image, polygon):
        import numpy as np
        return next(iter(self.cropper(bgr_image, np.asarray([polygon], dtype='float32'))))

    def recognize(self, image, language):
        result = next(iter(self._load(language)(image)))
        return {'text': str(result['rec_text']), 'confidence': float(result['rec_score']),
                'model': MODEL_NAMES[language]}

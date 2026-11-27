"""Contraste pour le repli et préparation d'une variante d'évaluation hors pipeline."""


def enhance_scan(bgr, max_pixels):
    import numpy as np
    from PIL import Image, ImageFilter, ImageOps
    if (not isinstance(bgr, np.ndarray) or bgr.dtype != np.uint8 or bgr.ndim != 3
            or bgr.shape[2] != 3 or not bgr.shape[0] or not bgr.shape[1]):
        raise ValueError('Image BGR uint8 non vide requise.')
    if bgr.shape[0] * bgr.shape[1] > max_pixels:
        raise ValueError('Image de repli trop grande pour max_pixels.')
    gray = Image.fromarray(bgr[:, :, ::-1]).convert('L')
    contrast = ImageOps.autocontrast(gray, cutoff=0)
    sharpened = contrast.filter(ImageFilter.UnsharpMask(radius=1, percent=80, threshold=3))
    result = np.asarray(sharpened.convert('RGB'))[:, :, ::-1].copy()
    return result, {'method': 'grayscale_autocontrast_unsharp.v1', 'cutoff': 0,
                    'unsharp': {'radius': 1, 'percent': 80, 'threshold': 3},
                    'source_size': [bgr.shape[1], bgr.shape[0]],
                    'output_size': [result.shape[1], result.shape[0]],
                    'geometry_changed': False, 'coordinate_transform': 'identity',
                    'warning': 'contrast_can_amplify_noise_or_alter_faint_diacritics'}


def prepare_scan_trial(bgr, max_pixels):
    """Build a denoised, binarized trial image and its inverse coordinate transform."""
    import cv2
    import numpy as np

    enhanced, _ = enhance_scan(bgr, max_pixels)
    gray = cv2.cvtColor(enhanced, cv2.COLOR_BGR2GRAY)
    denoised = cv2.medianBlur(gray, 3)
    _, binary = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    height, width = binary.shape
    lines = cv2.HoughLinesP(cv2.Canny(binary, 50, 150), 1, np.pi / 180, 80,
                            minLineLength=max(30, width // 8), maxLineGap=20)
    angles = []
    if lines is not None:
        for x0, y0, x1, y1 in lines[:, 0]:
            if x1 != x0:
                angle = float(np.degrees(np.arctan((int(y1) - int(y0)) / (int(x1) - int(x0)))))
                if abs(angle) <= 5:
                    angles.append(angle)
    angle = float(np.median(angles)) if len(angles) >= 5 else 0.0
    agreement = sum(abs(candidate - angle) <= .5 for candidate in angles)
    if abs(angle) < .25 or agreement * 4 < len(angles) * 3:
        angle = 0.0
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1)
    if angle:
        binary = cv2.warpAffine(binary, matrix, (width, height), flags=cv2.INTER_NEAREST,
                                borderValue=255)
    return cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR), {
        'method': 'median_otsu_horizontal_deskew.v1',
        'deskew_degrees': angle,
        'supporting_lines': agreement,
        'inverse_affine': cv2.invertAffineTransform(matrix).tolist(),
    }

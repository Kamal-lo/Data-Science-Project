FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 \
    PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 libgl1 libglib2.0-0 libxrender1 libsm6 libxext6 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY requirements*.txt /tmp/p2-requirements/
RUN cd /tmp/p2-requirements && \
    python -m pip install --timeout 90 --only-binary=paddlepaddle -r requirements.txt -c requirements-lock.txt && python -m pip check
COPY . /srv/P2_nlp_extraction/
RUN useradd --create-home --uid 10001 p2 && \
    mkdir -p P2_nlp_extraction/.cache/paddlex/official_models P2_nlp_extraction/outputs /documents && \
    chown -R p2:p2 P2_nlp_extraction/.cache P2_nlp_extraction/outputs
USER p2
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3).read()"
CMD ["python","-m","streamlit","run","P2_nlp_extraction/app.py","--server.address=0.0.0.0","--server.port=8501","--server.headless=true","--server.maxUploadSize=25","--browser.gatherUsageStats=false"]

ARG NVIDIA_PYTORCH_IMAGE=nvcr.io/nvidia/pytorch:26.03-py3
FROM ${NVIDIA_PYTORCH_IMAGE} AS base

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Etc/UTC

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libreoffice-writer \
    libgl1 \
    libglib2.0-0 \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ >/etc/timezone

# vLLM/Triton compiles small CUDA helper modules on first model load. Keep the
# compiler in the runtime image: the compilation happens after the container
# starts, not while this image is built.
ENV CC=gcc \
    CXX=g++ \
    TRITON_CACHE_DIR=/tmp/triton-cache \
    PYTHONUNBUFFERED=1

RUN mkdir -p "$TRITON_CACHE_DIR"

WORKDIR /app

COPY requirements.txt .
# The NGC image ships Debian's PyYAML without pip's RECORD metadata. Overlay it
# first so resolving application dependencies never tries to uninstall it.
RUN python -m pip install --no-cache-dir --ignore-installed PyYAML==6.0.2 \
    && python -m pip install --no-cache-dir -r requirements.txt

COPY . .

FROM base AS api
CMD ["uvicorn", "app.interfaces.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS worker
CMD ["python", "-m", "app.workers.worker_main"]

FROM base AS streamlit
EXPOSE 8501
CMD ["streamlit", "run", "scripts/upload_app.py", "--server.address=0.0.0.0", "--server.port=8501"]

FROM base AS qwen
CMD ["uvicorn", "app.interfaces.api.qwen_main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS paddle
CMD ["uvicorn", "app.interfaces.api.paddle_main:app", "--host", "0.0.0.0", "--port", "8000"]

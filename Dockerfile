FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SCIENTIST_LAB_DATA=/data

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-deps .

COPY app ./app
COPY tests ./tests
COPY .streamlit ./.streamlit

RUN useradd --create-home --uid 10001 lab && mkdir -p /data && chown lab:lab /data
USER lab

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4)"

# Inside the container Streamlit listens on all interfaces; docker-compose publishes the
# port on 127.0.0.1 only, so the app is reachable from localhost and nowhere else.
CMD ["streamlit", "run", "app/streamlit_app.py", "--server.address=0.0.0.0", "--server.port=8501"]

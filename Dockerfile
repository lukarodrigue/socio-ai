FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY socio_ia ./socio_ia
COPY playbooks ./playbooks
RUN pip install --no-cache-dir .
EXPOSE 8000
CMD ["uvicorn", "socio_ia.api:app", "--host", "0.0.0.0", "--port", "8000"]

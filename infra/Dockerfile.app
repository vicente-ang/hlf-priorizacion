# Imagen de la interfaz (app.py) para App Runner, ECS o una EC2. Construir desde la raíz del repositorio:
#   docker build -f infra/Dockerfile.app -t hlf-interfaz .
#   docker run -p 8501:8501 -e BEDROCK_MODEL_ID=... -e AWS_REGION=... hlf-interfaz
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt boto3
COPY . .
EXPOSE 8501
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]

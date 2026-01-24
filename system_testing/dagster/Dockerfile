FROM python:3.12-slim
RUN pip install dagster dagit dagster-webserver sqlalchemy
WORKDIR /opt/dagster/app
CMD ["dagster-webserver", "-h", "0.0.0.0", "-p", "3000", "-w", "workspace.yaml"]
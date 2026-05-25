FROM python:3.14.4-alpine

WORKDIR /usr/src/app/

COPY ./src/requirements.txt .

RUN pip install -r requirements.txt

COPY ./src/* .

CMD ["python", "main.py"]

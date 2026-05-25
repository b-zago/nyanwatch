FROM public.ecr.aws/lambda/python:3.14

COPY ./src/requirements.txt ${LAMBDA_TASK_ROOT}

RUN pip install -r requirements.txt

COPY ./src/* ${LAMBDA_TASK_ROOT}

CMD [ "main.lambda_handler" ]

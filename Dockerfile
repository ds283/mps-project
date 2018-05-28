FROM python:3.6-alpine3.7

RUN apk update
RUN apk add gcc libffi libffi-dev musl-dev linux-headers

RUN adduser -D mpsproject

WORKDIR /home/mpsproject

COPY requirements.txt requirements.txt
RUN python -m venv venv
RUN venv/bin/pip install -r requirements.txt
RUN venv/bin/pip install gunicorn

COPY app app
COPY migrations migrations
COPY mpsproject.py config.py boot.sh launch_celery.sh ./
RUN chmod +x boot.sh
RUN chmod +x launch_celery.sh

ENV FLASK_APP mpsproject.py

RUN chown -R mpsproject:mpsproject ./
USER mpsproject

EXPOSE 5000
ENTRYPOINT ["./boot.sh"]

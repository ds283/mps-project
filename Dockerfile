FROM python:3.6-alpine3.7

RUN apk update
RUN apk add gcc libffi libffi-dev musl-dev linux-headers mariadb-client

#RUN adduser -D mpsproject
RUN adduser -D -u 500 mpsproject

WORKDIR /home/mpsproject

COPY requirements.txt requirements.txt
RUN python -m venv venv
RUN venv/bin/pip install -r requirements.txt
RUN venv/bin/pip install gunicorn

COPY app app
COPY migrations migrations
COPY mpsproject.py celery_node.py config.py boot.sh launch_celery.sh launch_beat.sh launch_flower.sh ./
RUN chmod +x boot.sh
RUN chmod +x launch_celery.sh
RUN chmod +x launch_beat.sh
RUN chmod +x launch_flower.sh

ENV FLASK_APP mpsproject.py

RUN chown -R mpsproject:mpsproject ./
USER mpsproject

# web app and flower monitoring tool both run on port 5000
EXPOSE 5000

ENTRYPOINT ["./boot.sh"]

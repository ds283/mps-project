FROM pypy:3.6-slim-jessie

RUN apt-get update && apt-get install -qq -y build-essential gcc mariadb-client mysqltuner libssl-dev libjpeg-dev zlib1g-dev libglpk-dev glpk-utils coinor-cbc git --no-install-recommends

# uid = 500 needed for deployment on Amazon, where ecs-user has uid 500
RUN adduser --disabled-password --shell /bin/bash --gecos '' --uid 500 mpsproject

WORKDIR /home/mpsproject

COPY requirements.txt requirements.txt
RUN pip install --upgrade pip
RUN pypy3 -m venv venv
RUN venv/bin/pip install -r requirements.txt

COPY app app
COPY migrations migrations
COPY mpsproject.py serve.py celery_node.py boot.sh launch_celery.sh launch_beat.sh launch_flower.sh ./
RUN chmod +x boot.sh && chmod +x launch_celery.sh && chmod +x launch_beat.sh && chmod +x launch_flower.sh

ENV FLASK_APP mpsproject.py

RUN chown -R mpsproject:mpsproject ./
USER mpsproject

# web app and flower monitoring tool both run on port 5000
EXPOSE 5000

ENTRYPOINT ["./boot.sh"]

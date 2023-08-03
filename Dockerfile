FROM python:3.11-slim-bullseye

RUN apt-get update && apt-get install -qq -y build-essential gcc gfortran mariadb-client mysqltuner libssl-dev libjpeg-dev zlib1g-dev libglpk-dev glpk-utils coinor-cbc git pkg-config swig wget libcairo2-dev libmagic1 --no-install-recommends

# uid = 500 needed for deployment on Amazon, where ecs-user has uid 500
RUN adduser --disabled-password --shell /bin/bash --gecos '' --uid 500 mpsproject

RUN mkdir -p /scratch && chown mpsproject:mpsproject /scratch
RUN mkdir -p /mpsproject && chown mpsproject:mpsproject /mpsproject
WORKDIR /mpsproject

# install Python dependencies
COPY --chown=mpsproject:mpsproject requirements.txt ./

ENV VIRTUAL_ENV=/mpsproject/venv
USER mpsproject
RUN python3 -m venv ${VIRTUAL_ENV}

ENV PATH="$VIRTUAL_ENV/bin:$PATH"
USER mpsproject
RUN pip3 install -U pip setuptools wheel && pip3 install -U -r requirements.txt

COPY --chown=mpsproject:mpsproject app ./app/
COPY --chown=mpsproject:mpsproject migrations ./migrations/
COPY --chown=mpsproject:mpsproject basic_database ./basic_database/
COPY --chown=mpsproject:mpsproject mpsproject.py serve.py celery_node.py migrate.py boot.sh launch_celery.sh launch_beat.sh launch_flower.sh ./

USER mpsproject
RUN chmod +x boot.sh && chmod +x launch_celery.sh && chmod +x launch_beat.sh && chmod +x launch_flower.sh

ENV FLASK_ENV production
ENV FLASK_APP mpsproject.py

# web app and flower monitoring tool both run on port 5000
EXPOSE 5000

ENTRYPOINT ["./boot.sh"]

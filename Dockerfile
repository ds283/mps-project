FROM python:3.9-slim-bullseye

RUN apt-get update && apt-get install -qq -y build-essential gcc gfortran mariadb-client mysqltuner libssl-dev libjpeg-dev zlib1g-dev libglpk-dev glpk-utils coinor-cbc git pkg-config swig wget libcairo2-dev --no-install-recommends

# uid = 500 needed for deployment on Amazon, where ecs-user has uid 500
RUN adduser --disabled-password --shell /bin/bash --gecos '' --uid 500 mpsproject

WORKDIR /home/mpsproject

# install MuPDF; adapted from Ubuntu install script (https://github.com/pymupdf/PyMuPDF/blob/master/installation/ubuntu/ubuntu_pymupdf.sh)
# notice the Pip installation of PyMuPDF does not seem to work, because we get a cryptic error during
# compilation of the Python extension module
RUN wget https://mupdf.com/downloads/archive/mupdf-1.19.0-source.tar.gz && tar -zxvf mupdf-1.19.0-source.tar.gz
RUN wget https://github.com/pymupdf/PyMuPDF/archive/1.19.2.tar.gz && tar -zxvf 1.19.2.tar.gz

# replace config file in mupdf source
RUN rm mupdf-1.19.0-source/include/mupdf/fitz/config.h && cp PyMuPDF-1.19.2/fitz/_config.h mupdf-1.19.0-source/include/mupdf/fitz/config.h

RUN cd mupdf-1.19.0-source && export XCFLAGS="-fPIC" && make HAVE_X11=no HAVE_GLFW=no HAVE_GLUT=no HAVE_LEPTONICA=no HAVE_TESSERACT=no USE_SYSTEM_FREETYPE=no USE_SYSTEM_GUMBO=no USE_SYSTEM_HARFBUZZ=no USE_SYSTEM_JBIG2DEC=no USE_SYSTEM_OPENJPEG=no prefix=/usr/local
RUN cd mupdf-1.19.0-source && export XCFLAGS="-fPIC" && make HAVE_X11=no HAVE_GLFW=no HAVE_GLUT=no HAVE_LEPTONICA=no HAVE_TESSERACT=no USE_SYSTEM_FREETYPE=no USE_SYSTEM_GUMBO=no USE_SYSTEM_HARFBUZZ=no USE_SYSTEM_JBIG2DEC=no USE_SYSTEM_OPENJPEG=no prefix=/usr/local install

# install Python dependencies
COPY requirements.txt requirements.txt
ENV VIRTUAL_ENV=/home/mpsproject/venv
RUN python3 -m venv ${VIRTUAL_ENV}
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
RUN pip3 install -U pip setuptools wheel
RUN pip3 install -U -r requirements.txt

# replace PyMuPDF setup.py with our own version that has correct paths and library specifications
RUN rm PyMuPDF-1.19.2/setup.py
COPY PyMuPDF-setup.py PyMuPDF-1.19.2/setup.py

# build PyMuPDF
RUN cd PyMuPDF-1.19.2 && python3 setup.py build && python3 setup.py install

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

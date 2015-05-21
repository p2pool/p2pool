FROM ubuntu:14.04

RUN apt-get update -qq

RUN apt-get install -qqy git python gcc wget libpython-dev

# install pip
RUN wget https://bootstrap.pypa.io/get-pip.py
RUN python get-pip.py

# install twisted
RUN pip install twisted

# clone the repo
RUN git clone https://github.com/forrestv/p2pool
RUN chmod +x ./p2pool/run_p2pool.py

WORKDIR /p2pool
ENTRYPOINT ["./run_p2pool.py"]

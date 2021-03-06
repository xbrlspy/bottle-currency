#!/usr/bin/env python

import re
import os
import sys
import time
import redis
import bottle
import logging
import urllib2
import contextlib

from bottle import route
from config import cfget

STATIC_ROOT = os.path.join(os.path.dirname(__file__), 'static')

SERVICE_URL = "http://www.multimolti.com/apps/currencyapi"
# Mirrors:
#     http://www.lennart-moltrecht.com/apps/currencyapi/
#     http://tp1.com.ar/currency/
#     http://www.sann-gmbh.com/currencyapi/
#     http://static.hattrick-youthclub.org/currency/
#     http://financy.dbeuchert.com/

logging.basicConfig()
log = logging.getLogger('bottle-currency')
log.setLevel(logging.DEBUG)

rdb = redis.Redis(host=cfget('/redis.*/hostname', 'localhost'),
                  port=cfget('/redis.*/port', 6379),
                  password=cfget('/redis.*/password'))

def currencies(db=[]):
    if not db:
        with open("currencies.dat", 'r') as f:
            for line in f.readlines():
                symbol, title = line.strip().split("\t", 1)
                db.append((symbol, title))
    return db

class ConnectionError(Exception): pass
class ServiceError(Exception): pass

value_rx = re.compile(r'\d+\.\d+')

def get_upstream_rate(src, dst):
    url = ("%s/calculator.php?original=%s&target=%s&value=1.0") % (SERVICE_URL,
                                                                   src, dst)
    try:
        with contextlib.closing(urllib2.urlopen(url)) as stream:
            result = stream.read()
    except urllib2.URLError:
        log.exception("url error")
        raise ConnectionError("Can't connect upstream server")
    except urllib2.HTTPError:
        log.exception("http error")
        raise ConnectionError("Can't communicate upstream server")

    if result == "Currency Code not found":
        raise ServiceError("Currency code not found")
    if not re.match(r'\d+\.\d+', result):
        raise ServiceError("Unexpected upstream server response")

    return float(result)

@route('/')
def home():
    return bottle.template('home', currencies=currencies())

@route('/rate/:src#[A-Z]{3}#/:dst#[A-Z]{3}#')
def get_rate(src, dst):
    for i in range(3):
        try:
            rate = rdb.get(src + dst)
            if rate is None:
                rate = get_upstream_rate(src, dst)
                rdb.setex(src + dst, rate, 3*60*60)
            return '' if rate == '' else str(float(rate))
        except ConnectionError:
            time.sleep(1) # recoverable, retry after 1 sec
        except:
            log.exception("Unexpected error")
            raise # non-revocerable 
    raise # the 3rd connection error

@route('/static/:filename')
def serve_static(filename):
    return bottle.static_file(filename, root=STATIC_ROOT)

application = bottle.app()
application.catchall = False

if os.getenv('SELFHOST', False):
    bottle.run(application)


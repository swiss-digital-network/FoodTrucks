import math
from elasticsearch import Elasticsearch, exceptions
import os
import time
from flask import Flask, jsonify, request, render_template, make_response
import sys
import requests

es = Elasticsearch(host='es')

app = Flask(__name__)


def load_data_in_es():
    """ creates an index in elasticsearch """
    url = "http://data.sfgov.org/resource/rqzj-sfat.json"
    r = requests.get(url)
    data = r.json()
    print("Loading data in elasticsearch ...")
    for id, truck in enumerate(data):
        res = es.index(index="sfdata", doc_type="truck", id=id, body=truck)
    print("Total trucks loaded: ", len(data))


def safe_check_index(index, retry=1, max_retry=6):
    """ connect to ES with retry """
    if retry > max_retry:
        print("Out of retries. Bailing out...")
        sys.exit(1)
    try:
        status = es.indices.exists(index=index)
        return status
    except exceptions.ConnectionError as e:
        print('Unable to connect to ES. Retrying in {%d}s with exponential backoff...'.format(2**retry))
        time.sleep(2**retry)
        safe_check_index(index, retry+1)


def format_fooditems(string):
    items = [x.strip().lower() for x in string.split(":")]
    return items[1:] if items[0].find("cold truck") > -1 else items


def check_and_load_index():
    """ checks if index exits and loads the data accordingly """
    if not safe_check_index('sfdata'):
        print("Index not found...")
        load_data_in_es()

###########
### APP ###
###########


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/debug')
def test_es():
    resp = {}
    try:
        msg = es.cat.indices()
        resp["msg"] = msg
        resp["status"] = "success"
    except:
        resp["status"] = "failure"
        resp["msg"] = "Unable to reach ES"
    return jsonify(resp)


@app.route('/search')
def search():
    key = request.args.get('q')
    if not key:
        return jsonify({
            "status": "failure",
            "msg": "Please provide a query"
        })
    try:
        res = es.search(
            index="sfdata",
            body={
                "query": {"match": {"fooditems": key}},
                "size": 750  # max document size
            },
            request_timeout=5)
    except Exception as e:
        return make_response(
            jsonify({
                "status": "failure",
                "msg": "error in reaching elasticsearch"
            }),
            500
        )
    # filtering results
    vendors = set([x["_source"]["applicant"] for x in res["hits"]["hits"]])
    temp = {v: [] for v in vendors}
    fooditems = {v: "" for v in vendors}
    for r in res["hits"]["hits"]:
        applicant = r["_source"]["applicant"]
        if "location" in r["_source"]:
            truck = {
                "hours": r["_source"].get("dayshours", "NA"),
                "schedule": r["_source"].get("schedule", "NA"),
                "address": r["_source"].get("address", "NA"),
                "location": r["_source"]["location"]
            }
            fooditems[applicant] = r["_source"]["fooditems"]
            temp[applicant].append(truck)

    # "Generate a utilization % for a duration of interval seconds"
    utilization = 95
    interval = 2
    start_time = time.time()
    for i in range(0,int(interval)):
        while time.time()-start_time < utilization/100.0:
            a = math.sqrt(64*64*64*64*64)
        time.sleep(1-utilization/100.0)
        start_time += 1

    # building up results
    results = {"trucks": []}
    for v in temp:
        results["trucks"].append({
            "name": v,
            "fooditems": format_fooditems(fooditems[v]),
            "branches": temp[v],
            "drinks": fooditems[v].find("COLD TRUCK") > -1
        })
    hits = len(results["trucks"])
    locations = sum([len(r["branches"]) for r in results["trucks"]])

    return jsonify({
        "trucks": results["trucks"],
        "hits": hits,
        "locations": locations,
        "status": "success"
    })


if __name__ == "__main__":
    ENVIRONMENT_DEBUG = os.environ.get("DEBUG", False)
    check_and_load_index()
    app.run(host='0.0.0.0', port=5000, debug=ENVIRONMENT_DEBUG)

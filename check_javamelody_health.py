#!/usr/bin/env python3

import argparse
import nagiosplugin as nag
import operator
import json
from urllib.request import urlopen
import urllib.error
from sys import stderr
from collections import OrderedDict

__author__ = "Armon Dressler"
__license__ = "GPLv3"
__version__ = "0.4"
__email__ = "armon.dressler@gmail.com"


#check if tmpdir exists, writable
#chek for json output available

class CheckJavamelodyHealth(nag.Resource):

    def __init__(self,
                 metric,
                 tmpdir=None,
                 url=None,
                 url_timeout=10,
                 min=None,
                 max=None,
                 scan=None):
        self.url_timeout = url_timeout
        self.metric = metric
        self.tmpdir = tmpdir
        self.url = url + "?format=json&period=jour"

        self.min = min
        self.max = max
        self.scan = scan
        self.json_data = self._get_json_data()

    def _get_json_data(self):
        try:
            response = urlopen(self.url, timeout=self.url_timeout)
        except (urllib.error.URLError, TypeError) as e:
            print("Failed to grab data from {} .".format(self.url),file=stderr)
            raise
        return json.load(response)

    def _get_available_endpoints(self):
        valid_endpoint_types = ['http', 'sql', 'jpa', 'ejb', 'spring', 'guice', 'services', 'struts', 'jsf', 'jsp']
        application_name = self.json_data["list"][0]["application"].split("_")[0]
        endpoints = {"application": application_name,"endpoint_types": []}
        for endpoint_type in self.json_data["list"]:
            if endpoint_type.get("name","NONE") not in valid_endpoint_types:
                continue
            endpoints["endpoint_types"].append(
                OrderedDict([("endpoint_type", endpoint_type["name"]),
                             ("endpoint_size", len(self.json_data["list"][0]["requests"])),
                             ("requests", OrderedDict())
                             ])
            )
            self._get_available_requests(endpoint_type["name"])

    def _get_available_requests(self, endpoint_type):
        requests = OrderedDict()
        #
        #ENUM für endpoint_type erstellen
        #
        for request in self.json_data["list"][0][endpoint_type]["requests"][0]:
            print(request["name"])


    def heap_capacity_pct(self):
        part = self.json_data["list"][-1]["memoryInformations"]["usedMemory"]
        total = self.json_data["list"][-1]["memoryInformations"]["maxMemory"]
        return {
            "value": self._get_percentage(part, total),
            "name": "heap_memory_pct",
            "uom": "%",
            "min": 0,
            "max": 100}

    def thread_capacity_pct(self):
        part = self.json_data["list"][-1]["tomcatInformationsList"][0]["currentThreadCount"]
        total = self.json_data["list"][-1]["tomcatInformationsList"][0]["maxThreads"]
        return {
            "value": self._get_percentage(part, total),
            "name": "thread_capacity_pct",
            "uom": "%",
            "min": 0,
            "max": 100}

    def filedescriptor_capacity_pct(self):
        part = self.json_data["list"][-1]["unixOpenFileDescriptorCount"]
        total = self.json_data["list"][-1]["unixMaxFileDescriptorCount"]
        return {
            "value": self._get_percentage(part, total),
            "name": "filedescriptor_capacity_pct",
            "uom": "%",
            "min": 0,
            "max": 100}

#memoryInformations -> usedNonHeapMemory (nur absolute)
#memoryInformations -> garbageCollectionTimeMillis
#tomcatInformationsList -> requestCount
#scan http endpoints --> "list"[0]["requests"].names()
#dokumentieren + tests ...
#http://10.21.2.2:8180/triboni/cpx-admin/javamelody?period=jour&part=heaphisto
#https://github.com/sbower/nagios_javamelody_plugin/blob/master/src/main/java/advws/net/nagios/jmeoldy/core/CheckJMelody.java

    def _get_percentage(self, part, total):
        try:
            part = sum(part)
        except TypeError:
            pass
        try:
            total = sum(total)
        except TypeError:
            pass
        return round(part / total * 100, 2)

    def probe(self):
        if self.scan:
            self._get_available_endpoints()
            exit()
        metric_dict = operator.methodcaller(self.metric)(self)
        if self.min:
            metric_dict["min"] = self.min
        if self.max:
            metric_dict["max"] = self.max
        return nag.Metric(metric_dict["name"],
                          metric_dict["value"],
                          uom=metric_dict.get("uom"),
                          min=metric_dict.get("min"),
                          max=metric_dict.get("max"),
                          context=metric_dict.get("context"))


class CheckJavamelodyHealthContext(nag.ScalarContext):
    fmt_helper = {
        "heap_memory_pct": "{value}{uom} of total heap capacity in use.",
        "thread_capacity_pct": "{value}{uom} of max threads created.",
        "filedescriptor_capacity_pct": "{value}{uom} of max file descriptors in use."
    }

    def __init__(self, name, warning=None, critical=None,
                 fmt_metric='{name} is {valueunit}', result_cls=nag.Result):

        try:
            metric_helper_text = CheckJavamelodyHealthContext.fmt_helper[name]
        except KeyError:
            raise ValueError("Metric \"{}\" not found. Use --help to check for metrics available.".format(name))
        super(CheckJavamelodyHealthContext, self).__init__(name,
                                                           warning=warning,
                                                           critical=critical,
                                                           fmt_metric=metric_helper_text,
                                                           result_cls=result_cls)


class CheckJavamelodyHealthSummary(nag.Summary):

    def __init__(self, url):
        self.url = url

    def ok(self, results):
        if len(results.most_significant) > 1:
            info_message = ", ".join([str(result) for result in results.results])
        else:
            info_message = " ".join([str(result) for result in results.results])
        return "\"{}\" reports: {}".format(self.url,info_message)

    def problem(self, results):
        if len(results.most_significant) > 1:
            info_message = " ,".join([str(result) for result in results.results])
        else:
            info_message = " ".join([str(result) for result in results.results])
        return "\"{}\" reports: {}".format(self.url, info_message)


def parse_arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('-w', '--warning', metavar='RANGE', default='',
                        help='return warning if metric is outside RANGE,\
                            RANGE is defined as an number or an interval, e.g. 5:25 or :30  or 95:')
    parser.add_argument('-c', '--critical', metavar='RANGE', default='',
                        help='return critical if metric is outside RANGE,\
                            RANGE is defined as an number or an interval, e.g. 5:25 or :30  or 95:')
    parser.add_argument('-t', '--tmpdir', action='store', default='/tmp/check_javamelody_health',
                        help='path to directory to store delta files')
    parser.add_argument('-u', '--url', action='store',
                        help='url for javamelody instance, e.g. http://internal.example.com/sampleapp/javamelody')
    parser.add_argument('--max', action='store', default=None,
                        help='maximum value for performance data')
    parser.add_argument('--min', action='store', default=None,
                        help='minimum value for performance data')
    parser.add_argument('--metric', action='store', required=False,
                        help='Supported keywords: heap_usage')
    parser.add_argument('--scan', action='store_true', default=False,
                        help='Show ')
    parser.add_argument('-v', '--verbose', action='count', default=0,
                        help='increase output verbosity (use up to 3 times)')
    return parser.parse_args()


@nag.guarded
def main():
    args = parse_arguments()
    check = nag.Check(
        CheckJavamelodyHealth(
            args.metric,
            tmpdir=args.tmpdir,
            url=args.url,
            min=args.min,
            max=args.max,
            scan=args.scan),
        CheckJavamelodyHealthContext(args.metric, warning=args.warning, critical=args.critical),
        CheckJavamelodyHealthSummary(args.url))
    check.main(verbose=args.verbose)


if __name__ == '__main__':
    main()
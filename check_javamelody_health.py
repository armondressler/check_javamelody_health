#!/usr/bin/env python3

import argparse
import nagiosplugin as nag
import operator
import json
from urllib.request import urlopen
import urllib.error
from sys import stderr
from collections import OrderedDict
from os.path import join
from time import time

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
                 min=None,
                 max=None,
                 scan=None):
        self.url_timeout = 12
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
        except (urllib.error.URLError, TypeError):
            print("Failed to grab data from {} .".format(self.url), file=stderr)
            raise
        return json.load(response)

    def _get_available_endpoints(self):
        endpoints = OrderedDict()


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

    def request_count_timed(self, lapsize_in_secs=60):
        '''returns an average of total requests received across lapsize_in_secs,
        calculated from a historic value read from a file and the current value from the webinterface'''

        current_value = self.json_data["list"][-1]["tomcatInformationsList"][0]["requestCount"]
        current_time = int(time())
        try:
            _, historic_time, historic_value = self._get_json_metric_from_file("request_count_timed")
        except TypeError:
            #upon first execution, no historic value can be compared
            #to prevent extreme values (current_value - 0) we return 0
            metric_value = 0
        else:
            metric_value = (current_value - historic_value)/(current_time - historic_time)*lapsize_in_secs
        self._write_json_metric_to_file("request_count_timed",current_value)
        return {
            "value": metric_value,
            "name": "request_count_timed",
            "uom": "c",
            "min": 0}

    def _get_json_metric_from_file(self, metric):
        try:
            with open(join(self.tmpdir, metric), "r") as metric_file:
                metric_data = json.load(metric_file)
                for metric_tuple in metric_data:
                    if metric_tuple[0] == metric_tuple:
                        return metric_tuple
                else:
                    return None
        except FileNotFoundError:
            print("Failed to open file at {} .".format(join(self.tmpdir, metric)), file=stderr)
            return None

    def _write_json_metric_to_file(self, metric, value):
        current_unixtime = int(time())
        try:
            with open(join(self.tmpdir, metric), "w") as metric_file:
                json.dump((metric, current_unixtime, value), metric_file)
        except IOError:
            print("Failed to write to file at {} .".format(join(self.tmpdir, metric)), file=stderr)
            raise





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
        "filedescriptor_capacity_pct": "{value}{uom} of max file descriptors in use.",
        "request_count_timed": "{value} requests per minute received"
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
    parser.add_argument('--metric', action='store', required=True,
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
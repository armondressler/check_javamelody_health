#!/usr/bin/env python3

import argparse
import operator
import json
from urllib.request import urlopen
import urllib.error
from sys import stderr
from collections import OrderedDict
from os.path import join,exists,isdir
from os import makedirs
from time import time

try:
    import nagiosplugin as nag
except ImportError:
    print("Failed to import python module nagiosplugin,"
          "make sure to install it; e.g. pip3 install nagiosplugin", file=stderr)
    exit(3)


__author__ = "Armon Dressler"
__license__ = "GPLv3"
__version__ = "0.5"
__email__ = "armon.dressler@gmail.com"


class CheckJavamelodyHealth(nag.Resource):

    def __init__(self,
                 metric,
                 tmpdir=None,
                 url=None,
                 url_timeout=10,
                 min=None,
                 max=None,
                 scan=None,
                 request_path=None,
                 request_method=None,
                 endpoint_type=None):

        self.url_timeout = url_timeout
        self.lapsize_in_secs = 60
        self.metric = metric
        self.tmpdir = tmpdir
        self.url = url #+ "?format=json&period=jour" #TODO http://10.21.2.253:8180/sample/monitoring?format=json&period=tout
        self.uri_query = [("format", "json"), ("period", "jour")]
        self.min = min
        self.max = max
        self.scan = scan
        self.request_path = request_path
        self.request_method = request_method
        self.endpoint_type = endpoint_type
        self.json_data = self._get_json_data()
        if self.scan:
            self._prettyprint_available_endpoints(self._get_available_endpoints())
            exit()
            
    def _get_json_data(self,part=None):
        """Get metrics from javamelody web API
        valid values for part are listed under https://github.com/javamelody/javamelody/wiki/ExternalAPI#xml"""
        #valid_parts = ["threads", "counterSummaryPerClass", "heaphisto", "sessions",
        #               "mbeans", "jndi", "processes", "connections", "jvm", "database"]

        if part:
            self.uri_query.append(("part", part))
        self.url = self.url + "?" + "&".join([ item[0] + "=" + item[1] for item in self.uri_query])
        try:
            response = urlopen(self.url, timeout=self.url_timeout)
        except (urllib.error.HTTPError, urllib.error.URLError, TypeError):
            print("Failed to grab data from {} .".format(self.url), file=stderr)
            raise
        response = response.read().decode('utf-8').replace('\0', '')
        return json.loads(response)

    def _evaluate_with_historical_metric(self,metric,current_value):
        """Compares metric with numerical value current_value to a value previously stored in a file,
        as to make metrics such as total request count useful for monitoring."""
        current_time = int(time())
        try:
            _, historic_time, historic_value = self._get_json_metric_from_file(metric)
        except TypeError:
            #upon first execution, no historic value can be compared
            #to prevent extreme values (current_value - 0) we use 0
            print("No historical value found for metric {} in file {} .".format(
                metric, join(self.tmpdir, metric)), file=stderr)
            return 0
        else:
            time_difference = current_time - historic_time
            #prevent ZeroDivisionError
            if time_difference:
                metric_value = (current_value - historic_value)/time_difference*self.lapsize_in_secs
                return round(metric_value, 2)
            else:
                return 0

    def _get_tmpdir_file_prefix(self):
        return self.json_data["list"][-1]["pid"]

    def _get_absolute_path_for_tmpfile(self, metric):
        try:
            return self.tmpfile_absolute_path
        except AttributeError:
            filename = "_".join([self._get_tmpdir_file_prefix(), metric])
            self.tmpfile_absolute_path = join(self.tmpdir, filename)
            return self.tmpfile_absolute_path

    def _get_json_metric_from_file(self, metric):
        """read a metric which has been saved in a file from a previous run of the script"""
        absolute_filepath = self._get_absolute_path_for_tmpfile(metric)
        try:
            with open(absolute_filepath, "r") as metric_file:
                try:
                    metric_data = json.load(metric_file)
                except TypeError:
                    print("Failed to read json from file at {} .".format(absolute_filepath), file=stderr)
                    return None
                else:
                    return metric_data
        except FileNotFoundError:
            print("Failed to open file at {} .".format(absolute_filepath), file=stderr)
            return None
        except PermissionError:
            print("Failed to open file at {} missing permission.".format(absolute_filepath), file=stderr)
            return None

    def _write_json_metric_to_file(self, metric, value):
        """also tries to create dir if it doesnt exist already"""
        absolute_filepath = self._get_absolute_path_for_tmpfile(metric)
        current_unixtime = int(time())
        try:
            if not isdir(self.tmpdir):
                makedirs(self.tmpdir, exist_ok=True)
        except PermissionError:
            print("Failed to create directory {} .".format(self.tmpdir), file=stderr)
            raise
        try:
            with open(absolute_filepath, "w") as metric_file:
                json.dump((metric, current_unixtime, value), metric_file)
        except (IOError,PermissionError,NotADirectoryError):
            print("Failed to write to file at {} .".format(absolute_filepath), file=stderr)
            raise

    def _prettyprint_available_endpoints(self, endpoints):
        print(json.dumps(endpoints, sort_keys=True, indent=4))

    def _get_available_endpoints(self, endpoint_type=None):
        """Javamelody presents several metrics of type valid_endpoint_types , e.g. for http these might encompass
        requests to different paths"""
        if isinstance(endpoint_type, str):
            endpoint_type = [endpoint_type]
        valid_endpoint_types = ['http', 'sql', 'jpa', 'ejb', 'spring',
                                'guice', 'services', 'struts', 'jsf',
                                'jsp'] if not endpoint_type else endpoint_type
        try:
            application_name = self.json_data["list"][0]["application"].split("_")[0]
        except (TypeError,IndexError):
            print("Failed to grab application name from json data.", file=stderr)
            raise
        endpoints = {"application": application_name,"endpoint_types": []}

        for endpoint_dict in self.json_data["list"]:
            if endpoint_dict.get("name", "NONE") not in valid_endpoint_types:
                continue
            else:
                endpoints["endpoint_types"].append(
                    OrderedDict([("endpoint_type", endpoint_dict["name"]),
                                 ("endpoint_size", len(endpoint_dict["requests"])),
                                 ("requests",  self._get_available_requests(endpoint_dict,
                                                                            specific_path=self.request_path,
                                                                            specific_method=self.request_method))]
                                )
                )
        return endpoints

    def _get_available_requests(self, endpoint_dict, specific_path=None, specific_method=None):
        """returns a dict of requests and removes some clutter in their metrics"""
        requests = OrderedDict()
        interesting_submetrics = ["hits", "systemErrors", "responseSizesSum", "durationsSum"]
        joined_request_path = " ".join([specific_path, specific_method]) if specific_path else None

        for recorded_request in endpoint_dict["requests"]:
            if joined_request_path and recorded_request[0] != joined_request_path:
                continue
            requests[recorded_request[0]] = {}
            for submetric in interesting_submetrics:
                requests[recorded_request[0]][submetric] = recorded_request[1][submetric]
        return requests
    
    def _get_percentage(self, part, total):
        try:
            part = sum(part)
        except TypeError:
            pass
        try:
            total = sum(total)
        except TypeError:
            pass
        try:
            ret_val = round(part / total * 100, 2)
        except ZeroDivisionError:
            ret_val = 0
        return ret_val

    def probe(self):
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

    def heap_capacity_pct(self):
        part = self.json_data["list"][-1]["memoryInformations"]["usedMemory"]
        total = self.json_data["list"][-1]["memoryInformations"]["maxMemory"]
        return {
            "value": self._get_percentage(part, total),
            "name": "heap_capacity_pct",
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

    def file_descriptor_capacity_pct(self):
        part = self.json_data["list"][-1]["unixOpenFileDescriptorCount"]
        total = self.json_data["list"][-1]["unixMaxFileDescriptorCount"]
        return {
            "value": self._get_percentage(part, total),
            "name": "file_descriptor_capacity_pct",
            "uom": "%",
            "min": 0,
            "max": 100}

    def nonheap_memory_usage_total(self):
        """return the total usage of memory not allocated on the jvm heap in MB"""
        metric_value = self.json_data["list"][-1]["memoryInformations"]["usedNonHeapMemory"]
        metric_value /= 1024 ** 2
        return {
            "value": round(metric_value, 2),
            "name": "nonheap_memory_usage_total",
            "uom": "MB",
            "min": 0}

    def loaded_classes_count_total(self):
        """ returns currently loaded amount of classes..."""
        metric_value = self.json_data["list"][-1]["memoryInformations"]["loadedClassesCount"]
        return {
            "value": metric_value,
            "name": "loaded_classes_count_total",
            "uom": "c",
            "min": 0}

    def duration_per_hit_on_path(self):
        endpoint = self._get_available_endpoints(endpoint_type=self.endpoint_type)
        joined_request_path = " ".join([self.request_path, self.request_method])

        try:
            duration_sum_in_ms = endpoint["endpoint_types"][0]["requests"][joined_request_path]["durationsSum"]
            total_hits = endpoint["endpoint_types"][0]["requests"][joined_request_path]["hits"]
        except (KeyError,IndexError):
            #prevent UNKNOWN status when javamelody stats are reset
            duration_sum_in_ms = total_hits = 0
        try:
            metric_value = round(duration_sum_in_ms / total_hits, 1)
        except ZeroDivisionError:
            metric_value = 0

        return {
            "value": metric_value,
            "name": "duration_per_hit_on_path",
            "uom": "ms",
            "min": 0}

    def errors_per_hit_on_path(self):
        endpoint = self._get_available_endpoints(endpoint_type=self.endpoint_type)
        joined_request_path = " ".join([self.request_path, self.request_method])

        try:
            total_errors = endpoint["endpoint_types"][0]["requests"][joined_request_path]["systemErrors"]
            total_hits = endpoint["endpoint_types"][0]["requests"][joined_request_path]["hits"]
        except (KeyError,IndexError):
            #prevent UNKNOWN status when javamelody stats are reset
            total_errors = total_hits = 0

        metric_value = self._get_percentage(total_errors, total_hits)
        return {
            "value": metric_value,
            "name": "errors_per_hit_on_path",
            "uom": "%",
            "min": 0,
            "max": 100}

    def response_size_per_hit_on_path(self):
        endpoint = self._get_available_endpoints(endpoint_type=self.endpoint_type)
        joined_request_path = " ".join([self.request_path, self.request_method])

        try:
            total_response_size = endpoint["endpoint_types"][0]["requests"][joined_request_path]["responseSizesSum"]
            total_hits = endpoint["endpoint_types"][0]["requests"][joined_request_path]["hits"]
        except (KeyError,IndexError):
            #prevent UNKNOWN status when javamelody stats are reset
            total_response_size = total_hits = 0
        try:
            metric_value = round((total_response_size / total_hits)/1024, 2)
        except ZeroDivisionError:
            metric_value = 0

        return {
            "value": metric_value,
            "name": "response_size_per_hit_on_path",
            "uom": "kB",
            "min": 0}

    def request_count_timed(self):
        """ returns an average of total requests received across self.lapsize_in_secs,
        calculated from a historic value read from a file and the current value from the web interface"""

        current_value = self.json_data["list"][-1]["tomcatInformationsList"][0]["requestCount"]
        metric_value = self._evaluate_with_historical_metric("request_count_timed", current_value)
        self._write_json_metric_to_file("request_count_timed", current_value)
        return {
            "value": metric_value,
            "name": "request_count_timed",
            "uom": "c",
            "min": 0}

    def error_count_timed(self):
        """ returns an average of total errors encountered across self.lapsize_in_secs,
        calculated from a historic value read from a file and the current value from the web interface"""

        current_value = self.json_data["list"][-1]["tomcatInformationsList"][0]["errorCount"]
        metric_value = self._evaluate_with_historical_metric("error_count_timed",current_value)
        self._write_json_metric_to_file("error_count_timed", current_value)
        return {
            "value": metric_value,
            "name": "error_count_timed",
            "uom": "c",
            "min": 0}

    def garbage_collection_timed(self):
        """ returns an average of total required ms of garbage collection time,
        calculated from a historic value read from a file and the current value from the web interface"""

        current_value = self.json_data["list"][-1]["memoryInformations"]["garbageCollectionTimeMillis"]
        metric_value = self._evaluate_with_historical_metric("garbage_collection_timed",current_value)
        self._write_json_metric_to_file("garbage_collection_timed",current_value)
        return {
            "value": metric_value,
            "name": "garbage_collection_timed",
            "uom": "ms",
            "min": 0}


class CheckJavamelodyHealthContext(nag.ScalarContext):
    fmt_helper = {
        "heap_capacity_pct": "{value}{uom} of heap capacity exhausted.",
        "thread_capacity_pct": "{value}{uom} of thread capacity exhausted.",
        "file_descriptor_capacity_pct": "{value}{uom} of max file descriptors in use.",
        "nonheap_memory_usage_total": "{value}{uom} currently in use.",
        "loaded_classes_count_total": "{value} classes currently loaded.",
        "request_count_timed": "{value} requests per minute received.",
        "garbage_collection_timed": "{value}{uom} spent on gc for the last minute.",
        "error_count_timed": "{value} errors encountered per minute .",
        "duration_per_hit_on_path": "{value}{uom} needed on average.",
        "errors_per_hit_on_path": "{value}{uom} of requests failed.",
        "response_size_per_hit_on_path": "average response size at {value}{uom} ."}

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
    parser.add_argument('--max', action='store', default=None,
                        help='maximum value for performance data')
    parser.add_argument('--min', action='store', default=None,
                        help='minimum value for performance data')
    parser.add_argument('-t', '--tmpdir', action='store', default='/tmp/check_javamelody_health',
                        help='path to directory to store delta files')
    parser.add_argument('-u', '--url', action='store',
                        help='url for javamelody instance, e.g. http://internal.example.com/sampleapp/javamelody')
    parser.add_argument('-v', '--verbose', action='count', default=0,
                        help='increase output verbosity (use up to 3 times)')
    parser.add_argument('-p', '--request-path', action='store', default=None,
                        help='path to request, e.g. /users/list or /index.html ,\
                         see --scan option to list available paths')
    parser.add_argument('-e', '--endpoint-type', action='store', default="http",
                        help='type of request wanted, e.g. http, sql, jpa . Use --scan for listing.')
    parser.add_argument('-m', '--request-method', action='store', default="GET",
                        help='e.g. http verbs: GET, POST, PUT ...')
    execution_mode = parser.add_mutually_exclusive_group(required=True)
    execution_mode.add_argument('--metric', action='store', required=False, help='Supported keywords: {}'.format(
        ", ".join(CheckJavamelodyHealthContext.fmt_helper.keys())))
    execution_mode.add_argument('--scan', action='store_true', default=False, help='Show available endpoints')

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
            scan=args.scan,
            request_path=args.request_path,
            request_method=args.request_method,
            endpoint_type=args.endpoint_type),
        CheckJavamelodyHealthContext(args.metric, warning=args.warning, critical=args.critical),
        CheckJavamelodyHealthSummary(args.url))
    check.main(verbose=args.verbose)


if __name__ == '__main__':
    main()
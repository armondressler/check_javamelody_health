## check_javamelody_health
#### Nagios compliant monitoring script to report metrics from jvms using javamelody

The installation requires python3 and the module "nagiosplugin" (by Christian Kauhaus). Further requirements are javamelody (duh) and the xstream library for JSON exports. You can check for a working setup like so:
    wget 'mytomcat.example.local:8180/myapp/javamelody?format=json' 

The resulting json will be loaded with every execution of the plugin. For bigger applications with a large amount of paths / endpoints it can make sense to collapse some of the statistics into a single reference point by supplying a parameter in your web.xml, e.g.:

	<init-param>
		<param-name>url-exclude-pattern</param-name>
		<param-value>/static/.*</param-value>
	</init-param>

Refer to https://github.com/javamelody/javamelody/wiki/UserGuide#5-supplements-in-webxml for further information.

javamelody isn't ressource hungry, so running the plugin every 10 secs won't be an issue even on smaller setups. Make sure to test for yourself though.

For an icinga2 sample config, see directory "icinga2_sample_configs".


### Basic Usage:

#### Show option and their respective explanations.

    ./check_javamelody_health.py --help

#### Show available endpoints

    ./check_javamelody_health.py --url http://internal.example.com/sampleapp/javamelody --scan

#### Get current percentage of maximum heap in use

    ./check_javamelody_health.py --url http://internal.example.com/sampleapp/javamelody --metric heap_capacity_pct
    
```text
CHECKJAVAMELODYHEALTH OK - "http://internal.example.com/sampleapp/javamelody" reports: 11.96% of heap capacity exhausted. | heap_capacity_pct=11.96%;;;0;100
```

#### Get current percentage of maximum file descriptors opened and set check to warning if above 60% and critical if above 80% 

    ./check_javamelody_health.py --url http://internal.example.com/sampleapp/javamelody --metric file_descriptor_capacity_pct  -w :60 -c :80

```text
CHECKJAVAMELODYHEALTH OK - "http://internal.example.com/sampleapp/javamelody" reports: 1.49% of max file descriptors in use. | file_descriptor_capacity_pct=1.49%;60;80;0;100
``` 

#### Get current total of non heap memory in use

    ./check_javamelody_health.py --url http://internal.example.com/sampleapp/javamelody --metric nonheap_memory_usage_total -w :300 -c :500
    
```text  
CHECKJAVAMELODYHEALTH OK - "http://internal.example.com/sampleapp/javamelody" reports: 42.54MB currently in use. | nonheap_memory_usage_total=42.54MB;300;500;0
```

#### Get total requests received as an average of the last minute (will also report requests to javamelody itself)
Caveat: Javamelody does and will not provide an option for custom timeranges (https://github.com/javamelody/javamelody/issues/327). To get a reference point, we need to keep a state of previous executions for metrics which only report a total counter (e.g. total system errors encountered). For this reason every metric ending in *_timed creates a file in --tmpdir with the result of the previous execution. This plugin currently grabs all metrics by javamelody over the last 24 hours or "jour" in french (see \_\_init\_\_ of CheckJavamelodyHealth). Valid parameters are "jour", "semaine", "mois", "annee" and "tout". 

    ./check_javamelody_health.py --url http://internal.example.com/sampleapp/javamelody --metric request_count_timed -w :3000 -c :4000 --tmpdir /tmp/javamelody_state

```text
CHECKJAVAMELODYHEALTH OK - "http://internal.example.com/sampleapp/javamelody" reports: 12.0 requests per minute received. | request_count_timed=12.0c;3000;4000;0
```

#### Get average time needed to service GET requests to /hello.jsp

    ./check_javamelody_health.py --url http://internal.example.com/sampleapp/javamelody --metric duration_per_hit_on_path --request-path /hello.jsp --request-method GET -w :1500 -c :4000

```text
CHECKJAVAMELODYHEALTH OK - "http://internal.example.com/sampleapp/javamelody" reports: 0.8ms needed on average. | duration_per_hit_on_path=0.8ms;1500;4000;0
```

#### Get average error rate for specific path

    ./check_javamelody_health.py --url http://internal.example.com/sampleapp/javamelody --metric errors_per_hit_on_path --request-path /hello.jsp --request-method GET -w :5 -c :10
    
```text
CHECKJAVAMELODYHEALTH OK - "http://internal.example.com/sampleapp/javamelody" reports: 0.0% of requests failed. | errors_per_hit_on_path=0.0%;5;10;0;100
```

#### Get time spent on GC for last minute 

    ./check_javamelody_health.py --url http://internal.example.com/sampleapp/javamelody --metric garbage_collection_timed -w :5 -c :10

```text
CHECKJAVAMELODYHEALTH WARNING - "http://internal.example.com/sampleapp/javamelody" reports: 8.88ms spent on gc for the last minute. (outside range 0:5) | garbage_collection_timed=8.88ms;5;10;0
```

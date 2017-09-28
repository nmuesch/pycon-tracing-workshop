## Aaditya's Pycon talk slightly modified to fit a Support Onboarding Session. 
The purpose of this gist is to onboard Support to the importance of Datadog APM, what the UI loks like, how to get started setting it up, and a bit of the internals. This is definitely intended to be interactive and I'm happy to take any questions that come up along the way. 

## APM Demo
I'm going to quickly run through the Datadog APM demo so that you can be more familiarized with the UI components and where to look for all the pieces. 

## Prerequisites
If possible, it would be greatly helpful to finish these prior to the session, as it would save a bit of time on the downloading step. 
- Clone this repository somewhere on your Mac.
- [`docker`](https://www.docker.com/docker-mac)
- `docker-compose` - should come with the above Docker install
- `python`
- [A Datadog Account](https://app.datadoghq.com/signup)
- Run a preliminary `docker-compose up` in the cloned repo so things are properly downloaded. 

If you run into any issues, feel free to ping @nick on slack!

## A sample app in Flask begging to be traced
Here's an app that does a simple thing. It tells you what donut to pair with your craft brew. While it is contrived in its purpose, it probably has something in common with the apps you work on:

- It speaks HTTP
- To do its job, it must talk to datastores and external services.
- It has performance issues

## Get started
**Set your [Datadog API key](https://app.datadoghq.com/account/settings#api) in the docker-compose.yml file**

Now start up the sample app
```
$ docker-compose up
```

Now you should have running:
- A Flask app `web`, accepting HTTP requests
- A smaller Flask app `taster`, also accepting HTTP requests
- Redis, the backing datastore
- Datadog agent, a process that listens for, samples and aggregates traces

You can run the following command to verify these are running properly.

```
$ docker-compose ps
```

If all containers are running properly, you should see the following:

```
            Name                           Command               State                          Ports
-----------------------------------------------------------------------------------------------------------------------------
pycontracingworkshop_agent_1    /entrypoint.sh supervisord ...   Up      7777/tcp, 8125/udp, 0.0.0.0:8126->8126/tcp, 9001/tcp
pycontracingworkshop_redis_1    docker-entrypoint.sh redis ...   Up      6379/tcp
pycontracingworkshop_taster_1   python taster.py                 Up      0.0.0.0:5001->5001/tcp
pycontracingworkshop_web_1      python app.py                    Up      0.0.0.0:5000->5000/tcp
```

## Debugging
A few useful commands for debugging. You'll want these handy:

```
# Tail the logs for the trace-agent
docker exec -it pycontracingworkshop_agent_1 tail -f /var/log/datadog/trace-agent.log
```

```
# Tail the logs for web container
docker-compose logs -f web
```

## Step 1

Let's poke through the app and see how it works.

Vital Business Info about Beers and Donuts live in a SQL database.

Some information about Donuts changes rapidly, with the waves of baker opinion.
We store this time-sensitive information in a Redis-backed datastore called DonutDB.

The `DonutDB` class abstracts away some of the gory details and provides a simple API

Now let's look at the HTTP interface.

We can list the beers we have available
`curl -XGET localhost:5000/beers`

And the donuts we have available
`curl -XGET localhost:5000/donuts`

We can grab a beer by name
`curl -XGET localhost:5000/beers/ipa`

and a donut by name
`curl -XGET localhost:5000/donuts/jelly`

So far so good.


Things feel pretty speedy. But what happens when we try to find a donut that pairs well with our favorite beer?

`curl -XGET localhost:5000/pair/beer?name=ipa`

It feels slow! Slow enough that people might complain about it. Let's try to understand why

## Step 2 - Timing a Route

Anyone ever had to time a python function before?
There are several ways to do it, and they all involve some kind of timestamp math

With a decorator:
```python
def timing_decorator(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        start = time.time()
        try:
            ret = func(*args, **kwargs)
        finally:
            end = time.time()
        print("function %s took %.2f seconds" % (func.__name__, end-start))
        return ret
    return wrapped
```

With a context manager:
```python
class TimingContextManager(object):

    def __init__(self, name):
        self.name = name

    def __enter__(self):
        self.start = time.time()

    def __exit__(self, exc_type, exc_value, traceback):
        end = time.time()
        log.info("operation %s took %.2f seconds", self.name, end-self.:start)
```

This code already lives for you in `timing.py` and logs to `timing.log`. Let's wire these into the app, `app.py`.
```python
from timing import timing_decorator, TimingContextManager
...

@app.route('/pair/beer')
@timing_decorator
def pair():
    ...
```
Now, when our slow route gets hit, it dumps some helpful debug information to the log, `timing.log`.

You can start to see log lines such as:

```
function pair took 0.053 seconds
```

## Step 3 - Drill Down into subfunctions

The information about our bad route is still rather one-dimensional. The pair route does some fairly
complex things and i'm still not entirely sure _where_ it spends its time.

Let me use the timing context manager to drill down further.
```python
@app.route('/pair/beer')
@timing_decorator
def pair():
    name = request.args.get('name')

    with TimingContextManager("beer.query"):
        beer = Beer.query.filter_by(name=name).first()
    with TimingContextManager("donuts.query"):
        donuts = Donut.query.all()
    with TimingContextManager("match"):
        match = best_match(beer)

    return jsonify(match=match)
```


We now have a more granular view of where time is being spent
```
operation beer.query took 0.020 seconds
operation donuts.query took 0.005 seconds
operation match took 0.011 seconds
function pair took 0.041 seconds
```

But after several requests, this log becomes increasingly hard to scan! Let's add an identifier
to make sure we can trace the path of a request in its entirety.


## Step 4 - Request-scoped Metadata
You may have the notion of a "correlation ID" in your infrastructure already. The goal of this
identifier is almost always to inspect the lifecycle of a single request, especially one that moves
through several parts of code and several services.

Let's put a correlation ID into our timed routes! Hopefully this will make the log easier to parse


Add it to our decorator
```python
# timing.py

import uuid
...

def timing_decorator(func):
    def wrapped(*args, **kwargs):
        req_id = uuid.uuid1().int>>64 # a random 64-bit int
        from flask import g
        g.req_id = req_id
        ...
        log.info("req: %s, function %s took %.3f seconds", req_id, func.__name__, end-start)
```

... and to our context manager
```
# timing.py
class TimingContextManager(object):

    def __init__(self, name, req_id):
        self.name = name
        self.req_id = req_id

    def __exit__(...):
        ....
        log.info("req: %s, operation %s took %.3f seconds", self.req_id, self.name, end-self.start)
```

```
# app.py
with TimingContextManager('beer.query', g.req_id):
   ...
```

Now we see output like

```
req: 10743597937325899402, operation beer.query took 0.023 seconds
req: 10743597937325899402, operation donuts.query took 0.006 seconds
req: 10743597937325899402, operation match took 0.013 seconds
req: 10743597937325899402, function pair took 0.047 seconds
```


## Step 5 - A Step back
Let's think about what we've done so far. We've taken an app that was not particularly observable
and made it incrementally more so.

Our app now generates events
   - that are request-scoped.
   - and suggest a causal relationship

Remember our glossary - we're well on our way to having real traces!

One thing to note, this didn't come for free:
 - instrumentation is a non-zero overhead
 - instrumentation logic can leak into business logic in unsavory ways

What a good tracing client does for you is minimize the impact of both of these, while still emitting
rich, structured information.


## Step 6 - Datadog's python tracing client
Datadog's tracing client integrates with several commonly used python libraries.

Instrumentation can be explicit or implicit, and uses any library standards for telemetry that exist.
For most web frameworks this means Middleware. Let's add trace middleware to our flask integration

```python
# app.py

from ddtrace import tracer; tracer.debug_logging = True
tracer.configure(hostname="agent") # point to agent container

from ddtrace.contrib.flask import TraceMiddleware

app = Flask(__name__)
traced_app = TraceMiddleware(app, tracer, service="matchmaker")
```
The middleware is doing something very similar to the code you just wrote. It is:
- Timing requests
- Collecting request-scoped metadata
- Pinning some information to the global request context to allow causal relationships to be registered

Now that Datadog is doing the work for us at the middleware layer, lets drop out `@timing_decorator` and each `with TimingContextManager` in our `app.py` file.

If we hit our app a few more times, we can see that datadog has begun to display some information for us.
Let's walk through what you're seeing: _segue to demo

## Step 7 - Services, Names, and Resources
Now lets put the Tracing client in Debug mode to see what a Trace object looks like here. Its important to note that the trace client logs are going to be located wherever the application logs are!! For this example, we are going to change the application logs to print to stdout so we can see them on the terminal easier. 

All of the following is in app.py

```
import logging
import sys

# set the log level for testing purpose
root = logging.getLogger()
root.setLevel(logging.DEBUG)

ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)
root.addHandler(ch)
```

(The above is a bit outside the scope of APM, but is specific to setting up a logger for Python to use stdout so we can see it in the terminal.)

The important piece is the `tracer.debug_logging=True` at the top of the file!

Now that the Datadog Python Tracing client is in debug mode, lets restart our application and curl a few of our endpoints. 

Going back to our application logs, we should see something like the following:

```
name flask.request
id 7245111199352082055
trace_id 1044159332829592407
parent_id None
service matchmaker
resource ping
type http
start 1495094155.75
end 1495094155.92
duration 0.17s
error 0
tags
    http.status_code: 200
```

`name` is the name of the operation being traced

A `service` is the name of a set of processes that work together to provide a feature set.

A `resource` is a particular query to a service. For web apps this is usually the route or handler function

`id` is the unique ID of the current span

`trace_id` is the unique ID of the request containing this span

`parent_id` is the unique ID of the span that was the immediate causal predecessor of this span.

`tags` is the set of tags that have been applied at the span level

## Step 8 - Span Metadata
Now that we have seen what spans look like, lets add some custom data to them

a) Add a tag to your span. To do this, you can update your `app.py` file to modify the `pair` function

```
@app.route('/pair/beer')
def pair():
    span = tracer.current_span()
    name = request.args.get('name')
    beer = Beer.query.filter_by(name=name).first()
    donuts = Donut.query.all()
    match = best_match(beer)
    span.set_meta("beer", name)

    return jsonify(match=match)
```
    
   
Now lets hit this pair endpoint once more and see what our Span looks like in the UI. To do this, lets take the Trace ID and use that to format our URL. 

b) Visualizing an Error:

```
       name flask.request
         id 111755388383113288
   trace_id 11679350459822409529
  parent_id None
    service matchmaker
   resource pair
       type http
      start 1505868314.6839354
        end 1505868314.7376437
   duration 0.053708s
      error 1
       tags
            beer:ipa
            error.msg:Oh man, the pair endpoint failed!!! :scream:
            error.stack:Traceback (most recent call last):
   File "app.py", line 122, in pair
     raise ValueError("Oh man, the pair endpoint failed!!! :scream:")
 ValueError: Oh man, the pair endpoint failed!!! :scream:

            error.type:builtins.ValueError
            http.method:GET
            http.status_code:500
            http.url:http://localhost:5000/pair/beer
            system.pid:14
```

Lets take a look back into our account to see how that looks. 

## Step 9 - Questions?

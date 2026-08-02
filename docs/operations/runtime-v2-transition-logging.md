# Runtime V2 transition logging on Railway

This runbook maps the transition instrumentation to the process that emits it.
It intentionally documents observability only; it does not change Runtime V2
routing or transition behavior.

## Event names and log level

The transition decision and queue lifecycle are emitted at `INFO` by the Python
loggers for `app.flow_v2.executors._legacy` and `app.flow_v2.executor`:

- `RUNTIME_V2_CONDITION_EVALUATED` and
  `RUNTIME_V2_CONDITION_EXECUTOR_RETURN`: condition evaluation and the executor
  return contract;
- `RUNTIME_V2_NODE_EXECUTOR_RESULT`: result returned by every node executor;
- `RUNTIME_V2_ENQUEUE_TRANSITION_CALL` and
  `RUNTIME_V2_TRANSITION_QUEUE_STATE`: creation and state of the synchronous
  continuation queue;
- `RUNTIME_V2_TRANSITION_DEQUEUED`: consumption of that continuation;
- `RUNTIME_V2_MESSAGE_EXECUTOR_EXECUTED`: execution of a message node, including
  the incoming transition that led to it.

These are not `DEBUG` calls. Production can use `LOG_LEVEL=INFO` without
filtering them. Search by the exact uppercase value after `event=` rather than
the informal Python class or method name.

## Railway service mapping

`FlowV2RuntimeWorker` is a Python orchestration class, not an independently
started Railway process in this repository. Therefore a Railway service named
"runtime worker" only owns these logs if it has been configured out of band to
run an inbound-message consumer.

| Execution path | Process entry point | Railway logs containing transition events |
| --- | --- | --- |
| Normal production inbound webhook | API enqueues `process_incoming_message`; RQ runs `message_worker`, which calls `FlowRuntimeSelector` and `FlowV2RuntimeWorker` synchronously | The RQ **Worker** consuming `INCOMING_MESSAGE_QUEUE` (`high_priority` by default) |
| Direct/synchronous webhook or message-router path | FastAPI calls `FlowRuntimeSelector` in the request process | **Backend/API** |
| Scheduled Runtime V2 delay resume | `backend/worker.py` calls `FlowV2DelayWorker`, which invokes `FlowV2RuntimeWorker` | **Delay Worker** (sometimes labelled runtime worker operationally) |
| Outbound delivery after a message action | RQ invokes `send_worker.send_whatsapp_message` from `WHATSAPP_SEND_QUEUE` | **Send Worker**, but only send/delivery logs; not condition or transition events |

The default `backend/worker_rq.py` consumes both inbound and outbound queues. If
Railway splits those queues across services through environment variables,
inspect the service whose startup log lists `high_priority` for inbound Runtime
events. The outbound-only service will not execute the condition node.

## Deployment provenance check

For each Python service, compare Railway's deployed revision with the startup
marker `[RQ WORKER] started commit_sha=...` (workers) or its deployment metadata
(API and Delay Worker). All processes participating in the trace must use the
same full SHA.

Commit `51d43fd7e739d25f81a06d8dfc5adfdfd8e71321` is the merge commit that contains
the instrumentation commit `c3dc0e28a05b09ce5e6936d09dafef1b53a9a0f6` as its second parent. Consequently,
a process genuinely running `51d43fd7e739d25f81a06d8dfc5adfdfd8e71321`
contains all event calls listed above. Absence of those events for a Runtime V2
request points first to the wrong Railway service/queue, a process deployed at a
different revision, or a request that did not enter Runtime V2—not to DEBUG
filtering.

## Production trace checklist

1. Find the API event `incoming_message_enqueued` and retain its `job_id` and
   `correlation_id`.
2. In the inbound RQ Worker, match `event=job_started` for that job and confirm
   its startup `commit_sha` is the expected revision.
3. Filter that worker by `session_id` and the exact `RUNTIME_V2_*` event names.
4. Follow the selected `source_handle`, `transition_id`, and `next_node_id` from
   condition return through enqueue, dequeue, and message execution.
5. Consult Send Worker logs only after `send_enqueue`; they cannot identify who
   selected or enqueued the False branch inside Runtime V2.

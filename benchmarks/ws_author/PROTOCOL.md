# WS-Author 0.1: frozen task protocol

This is a synthetic design-authoring benchmark, separate from WS-Agent editing
and from the frozen WS-RealRoom engineering acceptance. Its predeclared task
and reference file is `tasks.json`. Each task starts in a separate empty project;
the provider receives the prompt but not the reference specification. No task
or expected result may be changed after the first evaluated run under the same
protocol version. Record the task file SHA-256 before running.

For creation tasks, a pass requires a real provider to propose the specified
rectangle or L-shaped simulated design with all requested metric dimensions,
opening types, host walls and offsets. The deterministic compiler must create
the expected parameterized objects and IFC4, independently parse and generate
their geometry, validate host opening/fill relationships, preserve provenance,
and report no geometry or topology issue. No unexpected object or unrequested
assumption is accepted. Units are evaluated after conversion to metres.

For missing information or impossible geometry, a pass requires no model
proposal and an explanation of the missing value or impossible geometry. The
task text states whether to ask or reject. Negative tasks cannot pass merely
because the provider or network crashed. T17 additionally requires the three
actual, confirmed operations described in the prompt and stable identities;
only producing an initial proposal does not pass it.

Provider outputs, tool calls, time, token usage and failures are retained per
task. Actual fees and human labor remain `NOT_MEASURED` when unavailable.
Automated confirmation is identified as automation. Synthetic design accuracy
does not establish real-world reconstruction accuracy. The set is development
evaluation, not evidence of generalization to withheld rooms or natural
language. A failed task remains in the denominator.

Performance Trace records where the time goes while you work: which actions were slow, what took the time inside them, and how often each feature was rebuilt. Use it when the workbench feels slow, and send the report with your model.

## How to use it

1. Click **Performance Trace** (Evaluate menu). It's ticked while it records.
2. Do the slow thing: open the tool, change the value, roll back, whatever it is.
3. Click **Performance Trace** again. A window shows the report; **Copy** puts it on the clipboard.

## Good to know

- The report lists the slowest actions first, each broken down into what was inside it (the
  recompute, each feature's rebuild, the panel, the preview), with the time FreeCAD took to draw
  the result after it. Then come the totals for each kind of work, and the counts: how many
  times each feature was rebuilt, and how many recomputes there were.
- It's also written to a file, named at the top of the window (`SolidDesign-perf.txt` in your
  temporary folder).
- While it records, an action slower than {{ slow }} s is also reported in the Report view as it
  happens.
- Tick **a full Python profile** in the report window for a detailed profile of the slowest
  actions next time. FreeCAD runs slower while that records.
- To trace from the moment FreeCAD starts (opening a file, say), start FreeCAD with the
  environment variable `SD_PROFILE=1` (or `SD_PROFILE=cprofile` for the full profile).

Troubleshooting
===============

.. contents::

Common Problems
---------------

Installation
~~~~~~~~~~~~

Python crashes due to library mismatches
........................................

Make sure that all commands are issued in after executing ``cmsenv``.  Also
attempt to clear out `$HOME/.local` and re-install.

Matplotlib fails to install
...........................

When using older CMSSW releases, `matplotlib` may fail to install.  This
can be solved by installing `numpy` first with ``pip install numpy``.

Configuration
~~~~~~~~~~~~~

Finding the right settings for resources
........................................

When running Lobster, the resources should get adjusted automatically.  To
avoid `WorkQueue` retrying tasks too often to find optimal settings, they
can be gathered from an old project via::

    find /my/working/directory -name "*.summary"|grep successful > mysummaries
    resource_monitor_histograms -L mysummaries -j 32 /my/web/output/directory my_project_name

Where ``-j 32`` should be adjusted to match the cores of the machine.
The output directory `/my/web/output/directory` then contains a file
`stats.json` with the resources that `WorkQueue` deems optimal, and
`index.html` has a tabular representation.

Mixing DBS and local datasets
.............................

Mixing datasets with inputs accessed via AAA and custom input configuration
is currently not supported.

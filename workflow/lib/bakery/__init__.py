"""
bakery: helps write and run the Snakefile of a HEP recasting workflow.

.. code-block:: python

    import bakery
    wf_util = bakery.WorkflowUtil()
    wf_util.load_workflow(workflow)

Modules
-------
:mod:`bakery.common`        errors, the path language, conversions
:mod:`bakery.config`        config sections, options, schema, checks; ``validate_config``
:mod:`bakery.project`       project root, folders, path templates, real/fake tools
:mod:`bakery.recipe`        the manifest recipe: ``expand_rows``, ``declare_lookup``, ``declare_column``
:mod:`bakery.tools`         :class:`Tools`: a config section of ``{name, enabled}`` entries, for ``over=`` / ``known=``
:mod:`bakery.manifest`      rows, formats, wildcards, selection
:mod:`bakery.jobValues`     ``param`` / ``param_path``: values of one job
:mod:`bakery.planner`       ``build_targets``: what each rule makes
:mod:`bakery.reports`       report, tables, help, confirmation screen, ``config.used.yaml``
:mod:`bakery.session`       the steps, in order (no Snakemake)
:mod:`bakery.readers`       Snakemake rules and DAG -> bakery objects
:mod:`bakery.workflowUtil`  :class:`WorkflowUtil`, what a Snakefile talks to

Only :mod:`bakery.readers` and :mod:`bakery.workflowUtil` use Snakemake (a test checks it).
"""
from .common import BakeryError, ConfigError, OrderError, RecipeError
from .workflowUtil import WorkflowUtil

__version__ = "0.9.1"
__all__ = ["WorkflowUtil", "BakeryError", "ConfigError", "RecipeError", "OrderError", "__version__"]

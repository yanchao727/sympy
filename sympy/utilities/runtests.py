"""
This is our testing framework.

Goals:

* it should be compatible with py.test and operate very similarly
  (or identically)
* doesn't require any external dependencies
* preferably all the functionality should be in this file only
* no magic, just import the test file and execute the test functions, that's it
* portable

"""
from __future__ import with_statement
import os
import sys
import inspect
import traceback
import pdb
import re
import linecache
from fnmatch import fnmatch
from timeit import default_timer as clock
import doctest as pdoctest # avoid clashing with our doctest() function
from doctest import DocTestFinder, DocTestRunner
import re as pre
import random
import subprocess
import signal

from sympy.core.cache import clear_cache

# Use sys.stdout encoding for ouput.
# This was only added to Python's doctest in Python 2.6, so we must duplicate
# it here to make utf8 files work in Python 2.5.
pdoctest._encoding = getattr(sys.__stdout__, 'encoding', None) or 'utf-8'

IS_PYTHON_3 = (sys.version_info[0] == 3)
IS_WINDOWS = (os.name == 'nt')


class Skipped(Exception):
    pass

def _indent(s, indent=4):
    """
    Add the given number of space characters to the beginning of
    every non-blank line in `s`, and return the result.
    If the string `s` is Unicode, it is encoded using the stdout
    encoding and the `backslashreplace` error handler.
    """
    # After a 2to3 run the below code is bogus, so wrap it with a version check
    if sys.version_info[0] < 3:
        if isinstance(s, unicode):
            s = s.encode(pdoctest._encoding, 'backslashreplace')
    # This regexp matches the start of non-blank lines:
    return re.sub('(?m)^(?!$)', indent*' ', s)

pdoctest._indent = _indent

# ovverride reporter to maintain windows and python3
def _report_failure(self, out, test, example, got):
    """
    Report that the given example failed.
    """
    s = self._checker.output_difference(example, got, self.optionflags)
    s = s.encode('raw_unicode_escape').decode('utf8', 'ignore')
    out(self._failure_header(test, example) + s)

if IS_PYTHON_3 and IS_WINDOWS:
    DocTestRunner.report_failure = _report_failure


def sys_normcase(f):
    if sys_case_insensitive:
        return f.lower()
    return f

def convert_to_native_paths(lst):
    """
    Converts a list of '/' separated paths into a list of
    native (os.sep separated) paths and converts to lowercase
    if the system is case insensitive.
    """
    newlst = []
    for i, rv in enumerate(lst):
        rv = os.path.join(*rv.split("/"))
        # on windows the slash after the colon is dropped
        if sys.platform == "win32":
            pos = rv.find(':')
            if pos != -1:
                if rv[pos+1] != '\\':
                    rv = rv[:pos+1] + '\\' + rv[pos+1:]
        newlst.append(sys_normcase(rv))
    return newlst

def get_sympy_dir():
    """
    Returns the root sympy directory and set the global value
    indicating whether the system is case sensitive or not.
    """
    global sys_case_insensitive

    this_file = os.path.abspath(__file__)
    sympy_dir = os.path.join(os.path.dirname(this_file), "..", "..")
    sympy_dir = os.path.normpath(sympy_dir)
    sys_case_insensitive = (os.path.isdir(sympy_dir) and
                        os.path.isdir(sympy_dir.lower()) and
                        os.path.isdir(sympy_dir.upper()))
    return sys_normcase(sympy_dir)

def isgeneratorfunction(object):
    """
    Return true if the object is a user-defined generator function.

    Generator function objects provides same attributes as functions.

    See isfunction.__doc__ for attributes listing.

    Adapted from Python 2.6.
    """
    CO_GENERATOR = 0x20
    if (inspect.isfunction(object) or inspect.ismethod(object)) and \
        object.func_code.co_flags & CO_GENERATOR:
        return True
    return False

def setup_pprint():
    from sympy import pprint_use_unicode, init_printing

    # force pprint to be in ascii mode in doctests
    pprint_use_unicode(False)

    # hook our nice, hash-stable strprinter
    init_printing(pretty_print=False)

def run_in_subprocess_with_hash_randomization(function, function_args=(),
    function_kwargs={}, command=sys.executable,
    module='sympy.utilities.runtests', force=False):
    """
    Run a function in a Python subprocess with hash randomization enabled.

    If hash randomization is not supported by the version of Python given, it
    returns False.  Otherwise, it returns the exit value of the command.  The
    function is passed to sys.exit(), so the return value of the function will
    be the return value.

    The environment variable PYTHONHASHSEED is used to seed Python's hash
    randomization.  If it is set, this function will return False, because
    starting a new subprocess is unnecessary in that case.  If it is not set,
    one is set at random, and the tests are run.  Note that if this
    environment variable is set when Python starts, hash randomization is
    automatically enabled.  To force a subprocess to be created even if
    PYTHONHASHSEED is set, pass ``force=True``.  This flag will not force a
    subprocess in Python versions that do not support hash randomization (see
    below), because those versions of Python do not support the ``-R`` flag.

    ``function`` should be a string name of a function that is importable from
    the module ``module``, like "_test".  The default for ``module`` is
    "sympy.utilities.runtests".  ``function_args`` and ``function_kwargs``
    should be a repr-able tuple and dict, respectively.  The default Python
    command is sys.executable, which is the currently running Python command.

    This function is necessary because the seed for hash randomization must be
    set by the environment variable before Python starts.  Hence, in order to
    use a predetermined seed for tests, we must start Python in a separate
    subprocess.

    Hash randomization was added in the minor Python versions 2.6.8, 2.7.3,
    3.1.5, and 3.2.3, and is enabled by default in all Python versions after
    and including 3.3.0.

    Examples
    ========

    >>> from sympy.utilities.runtests import (
    ... run_in_subprocess_with_hash_randomization)
    >>> # run the core tests in verbose mode
    >>> run_in_subprocess_with_hash_randomization("_test",
    ... function_args=("core",), function_kwargs={'verbose': True}) #doctest: +SKIP
    # Will return 0 if sys.executable supports hash randomization and tests
    # pass, 1 if they fail, and False if it does not support hash
    # randomization.

    """
    # Note, we must return False everywhere, not None, as subprocess.call will
    # sometimes return None.

    # First check if the Python version supports hash randomization
    # If it doesn't have this support, it won't reconize the -R flag
    p = subprocess.Popen([command, "-RV"], stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT)
    p.communicate()
    if p.returncode != 0:
        return False

    hash_seed = os.getenv("PYTHONHASHSEED")
    if not hash_seed:
        os.environ["PYTHONHASHSEED"] = str(random.randrange(2**32))
    else:
        if not force:
            return False
    # Now run the command
    commandstring = ("import sys; from %s import %s;sys.exit(%s(*%s, **%s))" %
                     (module, function, function, repr(function_args), repr(function_kwargs)))

    try:
        return subprocess.call([command, "-R", "-c", commandstring])
    finally:
        # Put the environment variable back, so that it reads correctly for
        # the current Python process.
        if hash_seed is None:
            del os.environ["PYTHONHASHSEED"]
        else:
            os.environ["PYTHONHASHSEED"] = hash_seed

def run_all_tests(test_args=(), test_kwargs={}, doctest_args=(),
    doctest_kwargs={}, examples_args=(), examples_kwargs={'quiet':True}):
    """
    Run all tests.

    Right now, this runs the regular tests (bin/test), the doctests
    (bin/doctest), the examples (examples/all.py), and the sage tests (see
    sympy/external/tests/test_sage.py).

    This is what ``setup.py test`` uses.

    You can pass arguments and keyword arguments to the test functions that
    support them (for now, test,  doctest, and the examples).  See the docstrings of those
    functions for a description of the available options.

    For example, to run the solvers tests with colors turned off:

    >>> from sympy.utilities.runtests import run_all_tests

    >>> run_all_tests(test_args=("solvers",), test_kwargs={"colors:False"}) # doctest: +SKIP

    """
    tests_successful = True

    try:
        # Regular tests
        if not test(*test_args, **test_kwargs):
            # some regular test fails, so set the tests_successful
            # flag to false and continue running the doctests
            tests_successful = False

        # Doctests
        print
        if not doctest(*doctest_args, **doctest_kwargs):
            tests_successful = False

        # Examples
        print
        sys.path.append("examples")
        from all import run_examples # examples/all.py
        if not run_examples(*examples_args, **examples_kwargs):
            tests_successful = False

        # Sage tests
        if not (sys.platform == "win32" or sys.version_info[0] == 3):
            # run Sage tests; Sage currently doesn't support Windows or Python 3
            dev_null = open(os.devnull, 'w')
            if subprocess.call("sage -v", shell=True, stdout=dev_null, stderr=dev_null) == 0:
                if subprocess.call("sage -python bin/test sympy/external/tests/test_sage.py", shell=True) != 0:
                    tests_successful = False

        if tests_successful:
            return
        else:
            # Return nonzero exit code
            sys.exit(1)
    except KeyboardInterrupt:
        print
        print("DO *NOT* COMMIT!")
        sys.exit(1)

def test(*paths, **kwargs):
    """
    Run tests in the specified test_*.py files.

    Tests in a particular test_*.py file are run if any of the given strings
    in ``paths`` matches a part of the test file's path. If ``paths=[]``,
    tests in all test_*.py files are run.

    Notes:

       * if sort=False, tests are run in random order (not default).
       * paths can be entered in native system format or in unix,
         forward-slash format.

    **Explanation of test results**

    ======  ===============================================================
    Output  Meaning
    ======  ===============================================================
    .       passed
    F       failed
    X       XPassed (expected to fail but passed)
    f       XFAILed (expected to fail and indeed failed)
    s       skipped
    w       slow
    T       timeout (e.g., when ``--timeout`` is used)
    K       KeyboardInterrupt (when running the slow tests with ``--slow``,
            you can interrupt one of them without killing the test runner)
    ======  ===============================================================


    Colors have no additional meaning and are used just to facilitate
    interpreting the output.

    Examples
    ========

    >>> import sympy

    Run all tests:

    >>> sympy.test()    # doctest: +SKIP

    Run one file:

    >>> sympy.test("sympy/core/tests/test_basic.py")    # doctest: +SKIP
    >>> sympy.test("_basic")    # doctest: +SKIP

    Run all tests in sympy/functions/ and some particular file:

    >>> sympy.test("sympy/core/tests/test_basic.py",
    ...        "sympy/functions")    # doctest: +SKIP

    Run all tests in sympy/core and sympy/utilities:

    >>> sympy.test("/core", "/util")    # doctest: +SKIP

    Run specific test from a file:

    >>> sympy.test("sympy/core/tests/test_basic.py",
    ...        kw="test_equality")    # doctest: +SKIP

    Run specific test from any file:

    >>> sympy.test(kw="subs")    # doctest: +SKIP

    Run the tests with verbose mode on:

    >>> sympy.test(verbose=True)    # doctest: +SKIP

    Don't sort the test output:

    >>> sympy.test(sort=False)    # doctest: +SKIP

    Turn on post-mortem pdb:

    >>> sympy.test(pdb=True)    # doctest: +SKIP

    Turn off colors:

    >>> sympy.test(colors=False)    # doctest: +SKIP

    Force colors, even when the output is not to a terminal (this is useful,
    e.g., if you are piping to ``less -r`` and you still want colors)

    >>> sympy.test(force_colors=False    # doctest: +SKIP

    The traceback verboseness can be set to "short" or "no" (default is
    "short")

    >>> sympy.test(tb='no')    # doctest: +SKIP

    You can disable running the tests in a separate subprocess using
    ``subprocess=False``.  This is done to support seeding hash randomization,
    which is enabled by default in the Python versions where it is supported.
    If subprocess=False, hash randomization is enabled/disabled according to
    whether it has been enabled or not in the calling Python process.
    However, even if it is enabled, the seed cannot be printed unless it is
    called from a new Python process.

    Hash randomization was added in the minor Python versions 2.6.8, 2.7.3,
    3.1.5, and 3.2.3, and is enabled by default in all Python versions after
    and including 3.3.0.

    If hash randomization is not supported ``subprocess=False`` is used
    automatically.

    >>> sympy.test(subprocess=False)     # doctest: +SKIP

    To set the hash randomization seed, set the environment variable
    ``PYTHONHASHSEED`` before running the tests.  This can be done from within
    Python using

    >>> import os
    >>> os,environ['PYTHONHASHSEED'] = 42 # doctest: +SKIP

    Or from the command line using

    $ PYTHONHASHSEED=42 ./bin/test

    If the seed is not set, a random seed will be chosen.

    Note that to reproduce the same hash values, you must use both the same as
    well as the same architecture (32-bit vs. 64-bit).

    """
    subprocess = kwargs.pop("subprocess", True)
    if subprocess:
        ret = run_in_subprocess_with_hash_randomization("_test",
            function_args=paths, function_kwargs=kwargs)
        if ret is not False:
            return not bool(ret)
    return not bool(_test(*paths, **kwargs))

def _test(*paths, **kwargs):
    """
    Internal function that actually runs the tests.

    All keyword arguments from ``test()`` are passed to this function except for
    ``subprocess``.

    Returns 0 if tests passed and 1 if they failed.  See the docstring of
    ``test()`` for more information.
    """
    verbose = kwargs.get("verbose", False)
    tb = kwargs.get("tb", "short")
    kw = kwargs.get("kw", "")
    post_mortem = kwargs.get("pdb", False)
    colors = kwargs.get("colors", True)
    force_colors = kwargs.get("force_colors", False)
    sort = kwargs.get("sort", True)
    seed = kwargs.get("seed", None)
    if seed is None:
        seed = random.randrange(100000000)
    timeout = kwargs.get("timeout", False)
    slow = kwargs.get("slow", False)
    r = PyTestReporter(verbose=verbose, tb=tb, colors=colors, force_colors=force_colors)
    t = SymPyTests(r, kw, post_mortem, seed)

    # Disable warnings for external modules
    import sympy.external
    sympy.external.importtools.WARN_OLD_VERSION = False
    sympy.external.importtools.WARN_NOT_INSTALLED = False

    test_files = t.get_test_files('sympy')

    if len(paths) == 0:
        t._testfiles.extend(test_files)
    else:
        paths = convert_to_native_paths(paths)
        matched = []
        for f in test_files:
            basename = os.path.basename(f)
            for p in paths:
                if p in f or fnmatch(basename, p):
                    matched.append(f)
                    break
        t._testfiles.extend(matched)

    return int(not t.test(sort=sort, timeout=timeout, slow=slow))

def doctest(*paths, **kwargs):
    """
    Runs doctests in all \*py files in the sympy directory which match
    any of the given strings in `paths` or all tests if paths=[].

    Note:
       o paths can be entered in native system format or in unix,
         forward-slash format.
       o files that are on the blacklist can be tested by providing
         their path; they are only excluded if no paths are given.

    Examples
    ========

    >>> import sympy

    Run all tests:
    >>> sympy.doctest() # doctest: +SKIP

    Run one file:
    >>> sympy.doctest("sympy/core/basic.py") # doctest: +SKIP
    >>> sympy.doctest("polynomial.rst") # doctest: +SKIP

    Run all tests in sympy/functions/ and some particular file:
    >>> sympy.doctest("/functions", "basic.py") # doctest: +SKIP

    Run any file having polynomial in its name, doc/src/modules/polynomial.rst,
    sympy/functions/special/polynomials.py, and sympy/polys/polynomial.py:

    >>> sympy.doctest("polynomial") # doctest: +SKIP

    The ``subprocess`` and ``verbose`` options are the same as with the function
    ``test()``.  See the docstring of that function for more information.
    """
    subprocess = kwargs.pop("subprocess", True)
    if subprocess:
        ret = run_in_subprocess_with_hash_randomization("_doctest",
            function_args=paths, function_kwargs=kwargs)
        if ret is not False:
            return not bool(ret)
    return not bool(_doctest(*paths, **kwargs))

def _doctest(*paths, **kwargs):
    """
    Internal function that actually runs the doctests.

    All keyword arguments from ``doctest()`` are passed to this function
    except for ``subprocess``.

    Returns 0 if tests passed and 1 if they failed.  See the docstrings of
    ``doctest()`` and ``test()`` for more information.
    """
    normal = kwargs.get("normal", False)
    verbose = kwargs.get("verbose", False)
    blacklist = kwargs.get("blacklist", [])
    blacklist.extend([
                    "doc/src/modules/mpmath", # needs to be fixed upstream
                    "sympy/mpmath", # needs to be fixed upstream
                    "doc/src/modules/plotting.rst", # generates live plots
                    # "sympy/plotting", # generates live plots
                    "sympy/plotting/pygletplot", # generates live plots
                    "sympy/utilities/compilef.py", # needs tcc
                    "sympy/utilities/autowrap.py", # needs installed compiler
                    "sympy/galgebra/GA.py", # needs numpy
                    "sympy/galgebra/latex_ex.py", # needs numpy
                    "sympy/conftest.py", # needs py.test
                    "sympy/utilities/benchmarking.py", # needs py.test
                    "examples/advanced/autowrap_integrators.py", # needs numpy
                    "examples/advanced/autowrap_ufuncify.py", # needs numpy
                    "examples/intermediate/mplot2d.py", # needs numpy and matplotlib
                    "examples/intermediate/mplot3d.py", # needs numpy and matplotlib
                    "examples/intermediate/sample.py", # needs numpy
                    ])
    blacklist = convert_to_native_paths(blacklist)

    # Disable warnings for external modules
    import sympy.external
    sympy.external.importtools.WARN_OLD_VERSION = False
    sympy.external.importtools.WARN_NOT_INSTALLED = False

    r = PyTestReporter(verbose)
    t = SymPyDocTests(r, normal)

    test_files = t.get_test_files('sympy')
    test_files.extend(t.get_test_files('examples', init_only=False))

    not_blacklisted = [f for f in test_files
                         if not any(b in f for b in blacklist)]
    if len(paths) == 0:
        t._testfiles.extend(not_blacklisted)
    else:
        # take only what was requested...but not blacklisted items
        # and allow for partial match anywhere or fnmatch of name
        paths = convert_to_native_paths(paths)
        matched = []
        for f in not_blacklisted:
            basename = os.path.basename(f)
            for p in paths:
                if p in f or fnmatch(basename, p):
                    matched.append(f)
                    break
        t._testfiles.extend(matched)

    # run the tests and record the result for this *py portion of the tests
    if t._testfiles:
        failed = not t.test()
    else:
        failed = False

    # N.B.
    # --------------------------------------------------------------------
    # Here we test *.rst files at or below doc/src. Code from these must
    # be self supporting in terms of imports since there is no importing
    # of necessary modules by doctest.testfile. If you try to pass *.py
    # files through this they might fail because they will lack the needed
    # imports and smarter parsing that can be done with source code.
    #
    test_files = t.get_test_files('doc/src', '*.rst', init_only=False)
    test_files.sort()

    not_blacklisted = [f for f in test_files
                            if not any(b in f for b in blacklist)]

    if len(paths) == 0:
        matched = not_blacklisted
    else:
        # Take only what was requested as long as it's not on the blacklist.
        # Paths were already made native in *py tests so don't repeat here.
        # There's no chance of having a *py file slip through since we
        # only have *rst files in test_files.
        matched =  []
        for f in not_blacklisted:
            basename = os.path.basename(f)
            for p in paths:
                if p in f or fnmatch(basename, p):
                    matched.append(f)
                    break

    setup_pprint()
    first_report = True
    for rst_file in matched:
        if not os.path.isfile(rst_file):
            continue
        old_displayhook = sys.displayhook
        try:
            # out = pdoctest.testfile(rst_file, module_relative=False, encoding='utf-8',
            #    optionflags=pdoctest.ELLIPSIS | pdoctest.NORMALIZE_WHITESPACE)
            out = sympytestfile(rst_file, module_relative=False, encoding='utf-8',
                optionflags=pdoctest.ELLIPSIS | pdoctest.NORMALIZE_WHITESPACE \
                            | pdoctest.IGNORE_EXCEPTION_DETAIL)
        finally:
            # make sure we return to the original displayhook in case some
            # doctest has changed that
            sys.displayhook = old_displayhook

        rstfailed, tested = out
        if tested:
            failed = rstfailed or failed
            if first_report:
                first_report = False
                msg = 'rst doctests start'
                lhead = '='*((r.terminal_width - len(msg))//2 - 1)
                rhead = '='*(r.terminal_width - 1 - len(msg) - len(lhead) - 1)
                print ' '.join([lhead, msg, rhead])
                print
            # use as the id, everything past the first 'sympy'
            file_id = rst_file[rst_file.find('sympy') + len('sympy') + 1:]
            print file_id, # get at least the name out so it is know who is being tested
            wid = r.terminal_width - len(file_id) - 1 #update width
            test_file = '[%s]' % (tested)
            report = '[%s]' % (rstfailed or 'OK')
            print ''.join([test_file,' '*(wid-len(test_file)-len(report)), report])

    # the doctests for *py will have printed this message already if there was
    # a failure, so now only print it if there was intervening reporting by
    # testing the *rst as evidenced by first_report no longer being True.
    if not first_report and failed:
        print
        print("DO *NOT* COMMIT!")

    return int(failed)

# The Python 2.5 doctest runner uses a tuple, but in 2.6+, it uses a namedtuple
# (which doesn't exist in 2.5-)
if sys.version_info[:2] > (2,5):
    from collections import namedtuple
    SymPyTestResults = namedtuple('TestResults', 'failed attempted')
else:
    SymPyTestResults = lambda a, b: (a, b)

def sympytestfile(filename, module_relative=True, name=None, package=None,
             globs=None, verbose=None, report=True, optionflags=0,
             extraglobs=None, raise_on_error=False,
             parser=pdoctest.DocTestParser(), encoding=None):
    """
    Test examples in the given file.  Return (#failures, #tests).

    Optional keyword arg "module_relative" specifies how filenames
    should be interpreted:

      - If "module_relative" is True (the default), then "filename"
         specifies a module-relative path.  By default, this path is
         relative to the calling module's directory; but if the
         "package" argument is specified, then it is relative to that
         package.  To ensure os-independence, "filename" should use
         "/" characters to separate path segments, and should not
         be an absolute path (i.e., it may not begin with "/").

      - If "module_relative" is False, then "filename" specifies an
        os-specific path.  The path may be absolute or relative (to
        the current working directory).

    Optional keyword arg "name" gives the name of the test; by default
    use the file's basename.

    Optional keyword argument "package" is a Python package or the
    name of a Python package whose directory should be used as the
    base directory for a module relative filename.  If no package is
    specified, then the calling module's directory is used as the base
    directory for module relative filenames.  It is an error to
    specify "package" if "module_relative" is False.

    Optional keyword arg "globs" gives a dict to be used as the globals
    when executing examples; by default, use {}.  A copy of this dict
    is actually used for each docstring, so that each docstring's
    examples start with a clean slate.

    Optional keyword arg "extraglobs" gives a dictionary that should be
    merged into the globals that are used to execute examples.  By
    default, no extra globals are used.

    Optional keyword arg "verbose" prints lots of stuff if true, prints
    only failures if false; by default, it's true iff "-v" is in sys.argv.

    Optional keyword arg "report" prints a summary at the end when true,
    else prints nothing at the end.  In verbose mode, the summary is
    detailed, else very brief (in fact, empty if all tests passed).

    Optional keyword arg "optionflags" or's together module constants,
    and defaults to 0.  Possible values (see the docs for details):

        DONT_ACCEPT_TRUE_FOR_1
        DONT_ACCEPT_BLANKLINE
        NORMALIZE_WHITESPACE
        ELLIPSIS
        SKIP
        IGNORE_EXCEPTION_DETAIL
        REPORT_UDIFF
        REPORT_CDIFF
        REPORT_NDIFF
        REPORT_ONLY_FIRST_FAILURE

    Optional keyword arg "raise_on_error" raises an exception on the
    first unexpected exception or failure. This allows failures to be
    post-mortem debugged.

    Optional keyword arg "parser" specifies a DocTestParser (or
    subclass) that should be used to extract tests from the files.

    Optional keyword arg "encoding" specifies an encoding that should
    be used to convert the file to unicode.

    Advanced tomfoolery:  testmod runs methods of a local instance of
    class doctest.Tester, then merges the results into (or creates)
    global Tester instance doctest.master.  Methods of doctest.master
    can be called directly too, if you want to do something unusual.
    Passing report=0 to testmod is especially useful then, to delay
    displaying a summary.  Invoke doctest.master.summarize(verbose)
    when you're done fiddling.
    """
    if package and not module_relative:
        raise ValueError("Package may only be specified for module-"
                         "relative paths.")

    # Relativize the path
    if not IS_PYTHON_3:
        text, filename = pdoctest._load_testfile(filename, package, module_relative)
        if encoding is not None:
            text = text.decode(encoding)
    else:
        text, filename = pdoctest._load_testfile(filename, package, module_relative, encoding)

    # If no name was given, then use the file's name.
    if name is None:
        name = os.path.basename(filename)

    # Assemble the globals.
    if globs is None:
        globs = {}
    else:
        globs = globs.copy()
    if extraglobs is not None:
        globs.update(extraglobs)
    if '__name__' not in globs:
        globs['__name__'] = '__main__'

    if raise_on_error:
        runner = pdoctest.DebugRunner(verbose=verbose, optionflags=optionflags)
    else:
        runner = SymPyDocTestRunner(verbose=verbose, optionflags=optionflags)

    # Read the file, convert it to a test, and run it.
    test = parser.get_doctest(text, globs, name, filename, 0)
    runner.run(test)

    if report:
        runner.summarize()

    if pdoctest.master is None:
        pdoctest.master = runner
    else:
        pdoctest.master.merge(runner)

    return SymPyTestResults(runner.failures, runner.tries)

class SymPyTests(object):

    def __init__(self, reporter, kw="", post_mortem=False,
                 seed=random.random()):
        self._post_mortem = post_mortem
        self._kw = kw
        self._count = 0
        self._root_dir = sympy_dir
        self._reporter = reporter
        self._reporter.root_dir(self._root_dir)
        self._testfiles = []
        self._seed = seed

    def test(self, sort=False, timeout=False, slow=False):
        """
        Runs the tests returning True if all tests pass, otherwise False.

        If sort=False run tests in random order.
        """
        if sort:
            self._testfiles.sort()
        else:
            from random import shuffle
            random.seed(self._seed)
            shuffle(self._testfiles)
        self._reporter.start(self._seed)
        for f in self._testfiles:
            try:
                self.test_file(f, sort, timeout, slow)
            except KeyboardInterrupt:
                print " interrupted by user"
                self._reporter.finish()
                raise
        return self._reporter.finish()

    def test_file(self, filename, sort=True, timeout=False, slow=False):
        clear_cache()
        self._count += 1
        gl = {'__file__':filename}
        random.seed(self._seed)
        try:
            if IS_PYTHON_3 and IS_WINDOWS:
                with open(filename, encoding="utf8") as f:
                    source = f.read()
                c = compile(source, filename, 'exec')
                exec c in gl
            else:
                execfile(filename, gl)
        except (SystemExit, KeyboardInterrupt):
            raise
        except ImportError:
            self._reporter.import_error(filename, sys.exc_info())
            return
        pytestfile = ""
        if "XFAIL" in gl:
            pytestfile = inspect.getsourcefile(gl["XFAIL"])
        pytestfile2 = ""
        if "SLOW" in gl:
            pytestfile2 = inspect.getsourcefile(gl["SLOW"])
        disabled = gl.get("disabled", False)
        if disabled:
            funcs = []
        else:
            # we need to filter only those functions that begin with 'test_'
            # that are defined in the testing file or in the file where
            # is defined the XFAIL decorator
            funcs = [gl[f] for f in gl.keys() if f.startswith("test_") and
                                                 (inspect.isfunction(gl[f])
                                                    or inspect.ismethod(gl[f])) and
                                                 (inspect.getsourcefile(gl[f]) == filename or
                                                   inspect.getsourcefile(gl[f]) == pytestfile or
                                                   inspect.getsourcefile(gl[f]) == pytestfile2)]
            if slow:
                funcs = [f for f in funcs if getattr(f, '_slow', False)]
            # Sorting of XFAILed functions isn't fixed yet :-(
            funcs.sort(key=lambda x: inspect.getsourcelines(x)[1])
            i = 0
            while i < len(funcs):
                if isgeneratorfunction(funcs[i]):
                # some tests can be generators, that return the actual
                # test functions. We unpack it below:
                    f = funcs.pop(i)
                    for fg in f():
                        func = fg[0]
                        args = fg[1:]
                        fgw = lambda: func(*args)
                        funcs.insert(i, fgw)
                        i += 1
                else:
                    i += 1
            # drop functions that are not selected with the keyword expression:
            funcs = [x for x in funcs if self.matches(x)]

        if not funcs:
            return
        self._reporter.entering_filename(filename, len(funcs))
        if not sort:
            random.shuffle(funcs)
        for f in funcs:
            self._reporter.entering_test(f)
            try:
                if getattr(f, '_slow', False) and not slow:
                    raise Skipped("Slow")
                if timeout:
                    self._timeout(f, timeout)
                else:
                    random.seed(self._seed)
                    f()
            except KeyboardInterrupt:
                if getattr(f, '_slow', False):
                    self._reporter.test_skip("KeyboardInterrupt")
                else:
                    raise
            except Exception:
                if timeout:
                    signal.alarm(0) # Disable the alarm. It could not be handled before.
                t, v, tr = sys.exc_info()
                if t is AssertionError:
                    self._reporter.test_fail((t, v, tr))
                    if self._post_mortem:
                        pdb.post_mortem(tr)
                elif t.__name__ == "Skipped":
                    self._reporter.test_skip(v)
                elif t.__name__ == "XFail":
                    self._reporter.test_xfail()
                elif t.__name__ == "XPass":
                    self._reporter.test_xpass(v)
                else:
                    self._reporter.test_exception((t, v, tr))
                    if self._post_mortem:
                        pdb.post_mortem(tr)
            else:
                self._reporter.test_pass()
        self._reporter.leaving_filename()

    def _timeout(self, function, timeout):
        def callback(x,y):
            signal.alarm(0)
            raise Skipped("Timeout")
        signal.signal(signal.SIGALRM, callback)
        signal.alarm(timeout) # Set an alarm with a given timeout
        function()
        signal.alarm(0) # Disable the alarm

    def matches(self, x):
        """
        Does the keyword expression self._kw match "x"? Returns True/False.

        Always returns True if self._kw is "".
        """
        if self._kw == "":
            return True
        return x.__name__.find(self._kw) != -1

    def get_test_files(self, dir, pat = 'test_*.py'):
        """
        Returns the list of test_*.py (default) files at or below directory
        `dir` relative to the sympy home directory.
        """
        dir = os.path.join(self._root_dir, convert_to_native_paths([dir])[0])

        g = []
        for path, folders, files in os.walk(dir):
            g.extend([os.path.join(path, f) for f in files if fnmatch(f, pat)])

        return [sys_normcase(gi) for gi in g]

class SymPyDocTests(object):

    def __init__(self, reporter, normal):
        self._count = 0
        self._root_dir = sympy_dir
        self._reporter = reporter
        self._reporter.root_dir(self._root_dir)
        self._normal = normal

        self._testfiles = []

    def test(self):
        """
        Runs the tests and returns True if all tests pass, otherwise False.
        """
        self._reporter.start()
        for f in self._testfiles:
            try:
                self.test_file(f)
            except KeyboardInterrupt:
                print " interrupted by user"
                self._reporter.finish()
                raise
        return self._reporter.finish()

    def test_file(self, filename):
        clear_cache()

        from StringIO import StringIO

        rel_name = filename[len(self._root_dir)+1:]
        dirname, file = os.path.split(filename)
        module = rel_name.replace(os.sep, '.')[:-3]

        if rel_name.startswith("examples"):
            # Examples files do not have __init__.py files,
            # So we have to temporarily extend sys.path to import them
            sys.path.insert(0, dirname)
            module = file[:-3] # remove ".py"
        setup_pprint()
        try:
            module = pdoctest._normalize_module(module)
            tests = SymPyDocTestFinder().find(module)
        except (SystemExit, KeyboardInterrupt):
            raise
        except ImportError:
            self._reporter.import_error(filename, sys.exc_info())
            return
        finally:
            if rel_name.startswith("examples"):
                del sys.path[0]

        tests = [test for test in tests if len(test.examples) > 0]
        # By default tests are sorted by alphabetical order by function name.
        # We sort by line number so one can edit the file sequentially from
        # bottom to top. However, if there are decorated functions, their line
        # numbers will be too large and for now one must just search for these
        # by text and function name.
        tests.sort(key=lambda x: -x.lineno)

        if not tests:
            return
        self._reporter.entering_filename(filename, len(tests))
        for test in tests:
            assert len(test.examples) != 0
            runner = SymPyDocTestRunner(optionflags=pdoctest.ELLIPSIS | \
                    pdoctest.NORMALIZE_WHITESPACE | pdoctest.IGNORE_EXCEPTION_DETAIL)
            old = sys.stdout
            new = StringIO()
            sys.stdout = new
            # If the testing is normal, the doctests get importing magic to
            # provide the global namespace. If not normal (the default) then
            # then must run on their own; all imports must be explicit within
            # a function's docstring. Once imported that import will be
            # available to the rest of the tests in a given function's
            # docstring (unless clear_globs=True below).
            if not self._normal:
                test.globs = {}
                # if this is uncommented then all the test would get is what
                # comes by default with a "from sympy import *"
                #exec('from sympy import *') in test.globs
            try:
                f, t = runner.run(test, out=new.write, clear_globs=False)
            except KeyboardInterrupt:
                raise
            finally:
                sys.stdout = old
            if f > 0:
                self._reporter.doctest_fail(test.name, new.getvalue())
            else:
                self._reporter.test_pass()
        self._reporter.leaving_filename()

    def get_test_files(self, dir, pat='*.py', init_only=True):
        """
        Returns the list of *py files (default) from which docstrings
        will be tested which are at or below directory `dir`. By default,
        only those that have an __init__.py in their parent directory
        and do not start with `test_` will be included.
        """
        def importable(x):
            """
            Checks if given pathname x is an importable module by checking for
            __init__.py file.

            Returns True/False.

            Currently we only test if the __init__.py file exists in the
            directory with the file "x" (in theory we should also test all the
            parent dirs).
            """
            init_py = os.path.join(os.path.dirname(x), "__init__.py")
            return os.path.exists(init_py)

        dir = os.path.join(self._root_dir, convert_to_native_paths([dir])[0])

        g = []
        for path, folders, files in os.walk(dir):
            g.extend([os.path.join(path, f) for f in files
                      if not f.startswith('test_') and fnmatch(f, pat)])
        if init_only:
            # skip files that are not importable (i.e. missing __init__.py)
            g = [x for x in g if importable(x)]

        return [sys_normcase(gi) for gi in g]

class SymPyDocTestFinder(DocTestFinder):
    """
    A class used to extract the DocTests that are relevant to a given
    object, from its docstring and the docstrings of its contained
    objects.  Doctests can currently be extracted from the following
    object types: modules, functions, classes, methods, staticmethods,
    classmethods, and properties.

    Modified from doctest's version by looking harder for code in the
    case that it looks like the the code comes from a different module.
    In the case of decorated functions (e.g. @vectorize) they appear
    to come from a different module (e.g. multidemensional) even though
    their code is not there.
    """

    def _find(self, tests, obj, name, module, source_lines, globs, seen):
        """
        Find tests for the given object and any contained objects, and
        add them to `tests`.
        """
        if self._verbose:
            print 'Finding tests in %s' % name

        # If we've already processed this object, then ignore it.
        if id(obj) in seen:
            return
        seen[id(obj)] = 1

        # Make sure we don't run doctests for classes outside of sympy, such
        # as in numpy or scipy.
        if inspect.isclass(obj):
            if obj.__module__.split('.')[0] != 'sympy':
                return

        # Find a test for this object, and add it to the list of tests.
        test = self._get_test(obj, name, module, globs, source_lines)
        if test is not None:
            tests.append(test)

        # Look for tests in a module's contained objects.
        if inspect.ismodule(obj) and self._recurse:
            for rawname, val in obj.__dict__.items():
                # Recurse to functions & classes.
                if inspect.isfunction(val) or inspect.isclass(val):
                    in_module = self._from_module(module, val)
                    if not in_module:
                        # double check in case this function is decorated
                        # and just appears to come from a different module.
                        pat = r'\s*(def|class)\s+%s\s*\(' % rawname
                        PAT = pre.compile(pat)
                        in_module = any(PAT.match(line) for line in source_lines)
                    if in_module:
                        try:
                            valname = '%s.%s' % (name, rawname)
                            self._find(tests, val, valname, module, source_lines, globs, seen)
                        except KeyboardInterrupt:
                            raise
                        except ValueError, msg:
                            raise
                        except Exception:
                            pass

        # Look for tests in a module's __test__ dictionary.
        if inspect.ismodule(obj) and self._recurse:
            for valname, val in getattr(obj, '__test__', {}).items():
                if not isinstance(valname, basestring):
                    raise ValueError("SymPyDocTestFinder.find: __test__ keys "
                                     "must be strings: %r" %
                                     (type(valname),))
                if not (inspect.isfunction(val) or inspect.isclass(val) or
                        inspect.ismethod(val) or inspect.ismodule(val) or
                        isinstance(val, basestring)):
                    raise ValueError("SymPyDocTestFinder.find: __test__ values "
                                     "must be strings, functions, methods, "
                                     "classes, or modules: %r" %
                                     (type(val),))
                valname = '%s.__test__.%s' % (name, valname)
                self._find(tests, val, valname, module, source_lines,
                           globs, seen)

        # Look for tests in a class's contained objects.
        if inspect.isclass(obj) and self._recurse:
            for valname, val in obj.__dict__.items():
                # Special handling for staticmethod/classmethod.
                if isinstance(val, staticmethod):
                    val = getattr(obj, valname)
                if isinstance(val, classmethod):
                    val = getattr(obj, valname).im_func

                # Recurse to methods, properties, and nested classes.
                if (inspect.isfunction(val) or
                     inspect.isclass(val) or
                     isinstance(val, property)):
                    in_module = self._from_module(module, val)
                    if not in_module:
                        # "double check" again
                        pat = r'\s*(def|class)\s+%s\s*\(' % valname
                        PAT = pre.compile(pat)
                        in_module = any(PAT.match(line) for line in source_lines)
                    if in_module:
                        valname = '%s.%s' % (name, valname)
                        self._find(tests, val, valname, module, source_lines,
                                   globs, seen)

    def _get_test(self, obj, name, module, globs, source_lines):
        """
        Return a DocTest for the given object, if it defines a docstring;
        otherwise, return None.
        """
        # Extract the object's docstring.  If it doesn't have one,
        # then return None (no test for this object).
        if isinstance(obj, basestring):
            docstring = obj
        else:
            try:
                if obj.__doc__ is None:
                    docstring = ''
                else:
                    docstring = obj.__doc__
                    if not isinstance(docstring, basestring):
                        docstring = str(docstring)
            except (TypeError, AttributeError):
                docstring = ''

        # Find the docstring's location in the file.
        lineno = self._find_lineno(obj, source_lines)

        if lineno is None:
            # if None, then _find_lineno couldn't find the docstring.
            # But IT IS STILL THERE.  Likely it was decorated or something
            # (i.e., @property docstrings have lineno == None)
            # TODO: Write our own _find_lineno that is smarter in this regard
            # Until then, just give it a dummy lineno.  This is just used for
            # sorting the tests, so the only bad effect is that they will appear
            # last instead of the order that they really are in the file.
            # lineno is also used to report the offending line of a failing
            # doctest, which is another reason to fix this.  See issue 1947.
            lineno = 0

        # Don't bother if the docstring is empty.
        if self._exclude_empty and not docstring:
            return None

        # Return a DocTest for this object.
        if module is None:
            filename = None
        else:
            filename = getattr(module, '__file__', module.__name__)
            if filename[-4:] in (".pyc", ".pyo"):
                filename = filename[:-1]
        return self._parser.get_doctest(docstring, globs, name,
                                        filename, lineno)

class SymPyDocTestRunner(DocTestRunner):
    """
    A class used to run DocTest test cases, and accumulate statistics.
    The `run` method is used to process a single DocTest case.  It
    returns a tuple `(f, t)`, where `t` is the number of test cases
    tried, and `f` is the number of test cases that failed.

    Modified from the doctest version to not reset the sys.displayhook (see
    issue 2041).

    See the docstring of the original DocTestRunner for more information.
    """

    def run(self, test, compileflags=None, out=None, clear_globs=True):
        """
        Run the examples in `test`, and display the results using the
        writer function `out`.

        The examples are run in the namespace `test.globs`.  If
        `clear_globs` is true (the default), then this namespace will
        be cleared after the test runs, to help with garbage
        collection.  If you would like to examine the namespace after
        the test completes, then use `clear_globs=False`.

        `compileflags` gives the set of flags that should be used by
        the Python compiler when running the examples.  If not
        specified, then it will default to the set of future-import
        flags that apply to `globs`.

        The output of each example is checked using
        `SymPyDocTestRunner.check_output`, and the results are formatted by
        the `SymPyDocTestRunner.report_*` methods.
        """
        self.test = test

        if compileflags is None:
            compileflags = pdoctest._extract_future_flags(test.globs)

        save_stdout = sys.stdout
        if out is None:
            out = save_stdout.write
        sys.stdout = self._fakeout

        # Patch pdb.set_trace to restore sys.stdout during interactive
        # debugging (so it's not still redirected to self._fakeout).
        # Note that the interactive output will go to *our*
        # save_stdout, even if that's not the real sys.stdout; this
        # allows us to write test cases for the set_trace behavior.
        save_set_trace = pdb.set_trace
        self.debugger = pdoctest._OutputRedirectingPdb(save_stdout)
        self.debugger.reset()
        pdb.set_trace = self.debugger.set_trace

        # Patch linecache.getlines, so we can see the example's source
        # when we're inside the debugger.
        self.save_linecache_getlines = pdoctest.linecache.getlines
        linecache.getlines = self.__patched_linecache_getlines

        try:
            return self.__run(test, compileflags, out)
        finally:
            sys.stdout = save_stdout
            pdb.set_trace = save_set_trace
            linecache.getlines = self.save_linecache_getlines
            if clear_globs:
                test.globs.clear()

# We have to override the name mangled methods.
SymPyDocTestRunner._SymPyDocTestRunner__patched_linecache_getlines = \
    DocTestRunner._DocTestRunner__patched_linecache_getlines
SymPyDocTestRunner._SymPyDocTestRunner__run = DocTestRunner._DocTestRunner__run
SymPyDocTestRunner._SymPyDocTestRunner__record_outcome = \
    DocTestRunner._DocTestRunner__record_outcome

class Reporter(object):
    """
    Parent class for all reporters.
    """
    pass

class PyTestReporter(Reporter):
    """
    Py.test like reporter. Should produce output identical to py.test.
    """

    def __init__(self, verbose=False, tb="short", colors=True, force_colors=False):
        self._verbose = verbose
        self._tb_style = tb
        self._colors = colors
        self._force_colors = force_colors
        self._xfailed = 0
        self._xpassed = []
        self._failed = []
        self._failed_doctest = []
        self._passed = 0
        self._skipped = 0
        self._exceptions = []
        self._terminal_width = None
        self._default_width = 80

        # this tracks the x-position of the cursor (useful for positioning
        # things on the screen), without the need for any readline library:
        self._write_pos = 0
        self._line_wrap = False

    def root_dir(self, dir):
        self._root_dir = dir

    @property
    def terminal_width(self):
        if self._terminal_width is not None:
            return self._terminal_width

        def findout_terminal_width():
            if sys.platform == "win32":
                # Windows support is based on:
                #
                #  http://code.activestate.com/recipes/440694-determine-size-of-console-window-on-windows/

                from ctypes import windll, create_string_buffer

                h = windll.kernel32.GetStdHandle(-12)
                csbi = create_string_buffer(22)
                res = windll.kernel32.GetConsoleScreenBufferInfo(h, csbi)

                if res:
                    import struct
                    (_, _, _, _, _, left, _, right, _, _, _) = struct.unpack("hhhhHhhhhhh", csbi.raw)
                    return right - left
                else:
                    return self._default_width

            if hasattr(sys.stdout, 'isatty') and not sys.stdout.isatty():
                return self._default_width # leave PIPEs alone

            try:
                process = subprocess.Popen(['stty', '-a'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                stdout = process.stdout.read()
                if sys.version_info[0] > 2:
                    stdout = stdout.decode("utf-8")
            except (OSError, IOError):
                pass
            else:
                # We support the following output formats from stty:
                #
                # 1) Linux   -> columns 80
                # 2) OS X    -> 80 columns
                # 3) Solaris -> columns = 80

                re_linux   = r"columns\s+(?P<columns>\d+);"
                re_osx     = r"(?P<columns>\d+)\s*columns;"
                re_solaris = r"columns\s+=\s+(?P<columns>\d+);"

                for regex in (re_linux, re_osx, re_solaris):
                    match = re.search(regex, stdout)

                    if match is not None:
                        columns = match.group('columns')

                        try:
                            return int(columns)
                        except ValueError:
                            pass

            return self._default_width

        width = findout_terminal_width()
        self._terminal_width = width

        return width

    def write(self, text, color="", align="left", width=None, force_colors=False):
        """
        Prints a text on the screen.

        It uses sys.stdout.write(), so no readline library is necessary.

        +-------+-------------------------------------------------------------+
        | color | choose from the colors below, "" means default color        |
        +-------+-------------------------------------------------------------+
        | align | left/right, left is a normal print, right is aligned on the |
        |       | right hand side of the screen, filled with " " if necessary |
        +-------+-------------------------------------------------------------+
        | width | the screen width                                            |
        +-------+-------------------------------------------------------------+

        """
        color_templates = (
            ("Black"       , "0;30"),
            ("Red"         , "0;31"),
            ("Green"       , "0;32"),
            ("Brown"       , "0;33"),
            ("Blue"        , "0;34"),
            ("Purple"      , "0;35"),
            ("Cyan"        , "0;36"),
            ("LightGray"   , "0;37"),
            ("DarkGray"    , "1;30"),
            ("LightRed"    , "1;31"),
            ("LightGreen"  , "1;32"),
            ("Yellow"      , "1;33"),
            ("LightBlue"   , "1;34"),
            ("LightPurple" , "1;35"),
            ("LightCyan"   , "1;36"),
            ("White"       , "1;37"),  )

        colors = {}

        for name, value in color_templates:
            colors[name] = value
        c_normal = '\033[0m'
        c_color = '\033[%sm'

        if width is None:
            width = self.terminal_width

        if align == "right":
            if self._write_pos+len(text) > width:
                # we don't fit on the current line, create a new line
                self.write("\n")
            self.write(" "*(width-self._write_pos-len(text)))

        if not self._force_colors and hasattr(sys.stdout, 'isatty') and not sys.stdout.isatty():
            # the stdout is not a terminal, this for example happens if the
            # output is piped to less, e.g. "bin/test | less". In this case,
            # the terminal control sequences would be printed verbatim, so
            # don't use any colors.
            color = ""
        if sys.platform == "win32":
            # Windows consoles don't support ANSI escape sequences
            color = ""

        if self._line_wrap:
            if text[0] != "\n":
                sys.stdout.write("\n")

        if IS_PYTHON_3 and IS_WINDOWS:
            text = text.encode('raw_unicode_escape').decode('utf8', 'ignore')

        if color == "":
            sys.stdout.write(text)
        else:
            sys.stdout.write("%s%s%s" % (c_color % colors[color], text, c_normal))
        sys.stdout.flush()
        l = text.rfind("\n")
        if l == -1:
            self._write_pos += len(text)
        else:
            self._write_pos = len(text)-l-1
        self._line_wrap = self._write_pos >= width
        self._write_pos %= width

    def write_center(self, text, delim="="):
        width = self.terminal_width
        if text != "":
            text = " %s " % text
        idx = (width-len(text)) // 2
        t = delim*idx + text + delim*(width-idx-len(text))
        self.write(t+"\n")

    def write_exception(self, e, val, tb):
        t = traceback.extract_tb(tb)
        # remove the first item, as that is always runtests.py
        t = t[1:]
        t = traceback.format_list(t)
        self.write("".join(t))
        t = traceback.format_exception_only(e, val)
        self.write("".join(t))

    def start(self, seed=None):
        self.write_center("test process starts")
        executable = sys.executable
        v = tuple(sys.version_info)
        python_version = "%s.%s.%s-%s-%s" % v
        self.write("executable:         %s  (%s)\n" % (executable, python_version))
        from .misc import ARCH
        self.write("architecture:       %s\n" % ARCH)
        from sympy.core.cache import USE_CACHE
        self.write("cache:              %s\n" % USE_CACHE)
        from sympy.polys.domains import GROUND_TYPES
        self.write("ground types:       %s\n" % GROUND_TYPES)
        if seed is not None:
            self.write("random seed:        %d\n" % seed)
        from .misc import HASH_RANDOMIZATION
        self.write("hash randomization: ")
        if HASH_RANDOMIZATION:
            hash_seed = os.getenv("PYTHONHASHSEED")
            if hash_seed:
                self.write("on (PYTHONHASHSEED=%s)\n" % hash_seed)
            else:
                # This should not happen.
                self.write("on (PYTHONHASHSEED not set)\n")
        else:
            self.write("off\n")
        self.write('\n')
        self._t_start = clock()

    def finish(self):
        self._t_end = clock()
        self.write("\n")
        global text, linelen
        text = "tests finished: %d passed, " % self._passed
        linelen = len(text)
        def add_text(mytext):
            global text, linelen
            """Break new text if too long."""
            if linelen + len(mytext) > self.terminal_width:
                text += '\n'
                linelen = 0
            text += mytext
            linelen += len(mytext)

        if len(self._failed) > 0:
            add_text("%d failed, " % len(self._failed))
        if len(self._failed_doctest) > 0:
            add_text("%d failed, " % len(self._failed_doctest))
        if self._skipped > 0:
            add_text("%d skipped, " % self._skipped)
        if self._xfailed > 0:
            add_text("%d expected to fail, " % self._xfailed)
        if len(self._xpassed) > 0:
            add_text("%d expected to fail but passed, " % len(self._xpassed))
        if len(self._exceptions) > 0:
            add_text("%d exceptions, " % len(self._exceptions))
        add_text("in %.2f seconds" % (self._t_end - self._t_start))


        if len(self._xpassed) > 0:
            self.write_center("xpassed tests", "_")
            for e in self._xpassed:
                self.write("%s: %s\n" % (e[0], e[1]))
            self.write("\n")

        if self._tb_style != "no" and len(self._exceptions) > 0:
            #self.write_center("These tests raised an exception", "_")
            for e in self._exceptions:
                filename, f, (t, val, tb) = e
                self.write_center("", "_")
                if f is None:
                    s = "%s" % filename
                else:
                    s = "%s:%s" % (filename, f.__name__)
                self.write_center(s, "_")
                self.write_exception(t, val, tb)
            self.write("\n")

        if self._tb_style != "no" and len(self._failed) > 0:
            #self.write_center("Failed", "_")
            for e in self._failed:
                filename, f, (t, val, tb) = e
                self.write_center("", "_")
                self.write_center("%s:%s" % (filename, f.__name__), "_")
                self.write_exception(t, val, tb)
            self.write("\n")

        if self._tb_style != "no" and len(self._failed_doctest) > 0:
            #self.write_center("Failed", "_")
            for e in self._failed_doctest:
                filename, msg = e
                self.write_center("", "_")
                self.write_center("%s" % filename, "_")
                self.write(msg)
            self.write("\n")

        self.write_center(text)
        ok = len(self._failed) == 0 and len(self._exceptions) == 0 and \
                len(self._failed_doctest) == 0
        if not ok:
            self.write("DO *NOT* COMMIT!\n")
        return ok

    def entering_filename(self, filename, n):
        rel_name = filename[len(self._root_dir)+1:]
        self._active_file = rel_name
        self._active_file_error = False
        self.write(rel_name)
        self.write("[%d] " % n)

    def leaving_filename(self):
        if self._colors:
            self.write(" ")
            if self._active_file_error:
                self.write("[FAIL]", "Red", align="right")
            else:
                self.write("[OK]", "Green", align="right")
        self.write("\n")
        if self._verbose:
            self.write("\n")

    def entering_test(self, f):
        self._active_f = f
        if self._verbose:
            self.write("\n"+f.__name__+" ")

    def test_xfail(self):
        self._xfailed += 1
        self.write("f", "Green")

    def test_xpass(self, v):
        if sys.version_info[:2] < (2, 6):
            message = getattr(v, 'message', '')
        else:
            message = str(v)
        self._xpassed.append((self._active_file, message))
        self.write("X", "Green")

    def test_fail(self, exc_info):
        self._failed.append((self._active_file, self._active_f, exc_info))
        self.write("F", "Red")
        self._active_file_error = True

    def doctest_fail(self, name, error_msg):
        # the first line contains "******", remove it:
        error_msg = "\n".join(error_msg.split("\n")[1:])
        self._failed_doctest.append((name, error_msg))
        self.write("F", "Red")
        self._active_file_error = True

    def test_pass(self, char="."):
        self._passed += 1
        if self._verbose:
            self.write("ok", "Green")
        else:
            self.write(char, "Green")

    def test_skip(self, v):
        if sys.version_info[:2] < (2, 6):
            message = getattr(v, 'message', '')
        else:
            message = str(v)
        self._skipped += 1
        char = "s"
        if message == "KeyboardInterrupt": char = "K"
        elif message == "Timeout": char = "T"
        elif message == "Slow": char = "w"
        self.write(char, "Blue")
        if self._verbose:
            self.write(" - ", "Blue")
            self.write(message, "Blue")

    def test_exception(self, exc_info):
        self._exceptions.append((self._active_file, self._active_f, exc_info))
        self.write("E", "Red")
        self._active_file_error = True

    def import_error(self, filename, exc_info):
        self._exceptions.append((filename, None, exc_info))
        rel_name = filename[len(self._root_dir)+1:]
        self.write(rel_name)
        self.write("[?]   Failed to import", "Red")
        if self._colors:
            self.write(" ")
            self.write("[FAIL]", "Red", align="right")
        self.write("\n")

sympy_dir = get_sympy_dir()

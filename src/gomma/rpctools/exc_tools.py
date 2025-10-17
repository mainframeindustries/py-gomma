import importlib
import traceback
import warnings


class RemoteException(Exception):
    """
    The exception which is created out of the remote exception.  We cannot reconstruct the remote exception precisely
    because its type may not exist locally.
    Also, there is no way in python to customize exception formatting.
    """

    def __init__(self, *args):
        super().__init__(*args)
        self.exception = args[0]

    @classmethod
    def FromTracebackException(cls, tbe):
        # If we provide a single argument which isn't something simple, then it doesn't
        # get formatted with the exception.  So, provide two
        result = cls(tbe, list(tbe.format()))
        return result

    @classmethod
    def FromStrings(cls, strings):
        # If we provide a single argument which isn't something simple, then it doesn't
        # get formatted with the exception.  So, provide two
        result = cls(list(strings))
        return result


class FakeException(type):
    """
    Represent an exc_type of a TracebackException which isn't found here.
    TracebackException.format() expects `exc_type` to be a real type.
    """

    @classmethod
    def create(cls, module, name, reprstr):
        """
        Dynamically create a new exception type to be used.
        """
        fake = cls(name, (Exception,), {})
        fake.__module__ = module
        fake.repr = reprstr
        return fake


# Methods to serialize / deserialize tracebackexceptions

_traceback_exception_attrs = ["__suppress_context__", "_str"]
_traceback_exception_syntax_attrs = [
    "filename",
    "lineno",
    "end_lineno",
    "text",
    "offset",
    "end_offset",
    "msg",
]


def traceback_exception_serialize(te: traceback.TracebackException) -> dict:
    result = {
        "type": "TracebackException:1.0",
        "__cause__": traceback_exception_serialize(te.__cause__) if te.__cause__ else None,
        "__context__": traceback_exception_serialize(te.__context__) if te.__context__ else None,
        "stack": stack_summary_serialize(te.stack),
    }

    # Handle both old and new exception type attributes
    if hasattr(te, "exc_type_str"):
        # Python 3.13+ approach
        result["exc_type_str"] = te.exc_type_str
        result["exc_type_module"] = getattr(te, "exc_type_module", None)
        result["exc_type_qualname"] = getattr(te, "exc_type_qualname", None)
        # Still include the old format for backward compatibility
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            if hasattr(te, "exc_type"):
                result["exc_type"] = exc_type_serialize(te.exc_type)
    else:
        # Pre-Python 3.13 approach
        result["exc_type"] = exc_type_serialize(te.exc_type)

    for name in _traceback_exception_attrs:
        if hasattr(te, name):
            result[name] = getattr(te, name)

    # Handle syntax errors
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        if hasattr(te, "exc_type") and hasattr(te.exc_type, "__name__"):
            if issubclass(te.exc_type, SyntaxError):
                se = {}
                for name in _traceback_exception_syntax_attrs:
                    se[name] = getattr(te, name, None)
                result["syntax_error"] = se
            else:
                result["syntax_error"] = None
        elif hasattr(te, "exc_type_str") and "SyntaxError" in te.exc_type_str:
            # Handle syntax errors in Python 3.13+
            se = {}
            for name in _traceback_exception_syntax_attrs:
                se[name] = getattr(te, name, None)
            result["syntax_error"] = se
        else:
            result["syntax_error"] = None

    return result


def _transfer_traceback_attributes(new_result, old_result, te_data):
    """Helper function to transfer attributes from serialized data to new TracebackException"""
    new_result.__cause__ = old_result.__cause__
    new_result.__context__ = old_result.__context__
    new_result.stack = old_result.stack

    # Set other attributes
    for name in _traceback_exception_attrs:
        if hasattr(new_result, name) and name in te_data:
            setattr(new_result, name, te_data[name])

    # Handle syntax error attributes
    if te_data.get("syntax_error"):
        for name in _traceback_exception_syntax_attrs:
            value = te_data["syntax_error"].get(name)
            if value is not None and hasattr(new_result, name):
                setattr(new_result, name, value)

    return new_result


def traceback_exception_deserialize(te: dict) -> traceback.TracebackException:
    tbtype = te.get("type", "TracebackException:1.0")
    assert tbtype in ["TracebackException:1.0"]

    # construct a dummy TracebackException and fill its attributes
    # Use SyntaxError if we're dealing with syntax error data, otherwise RuntimeError
    if te.get("syntax_error"):
        try:
            raise SyntaxError("dummy")
        except SyntaxError as e:
            result = traceback.TracebackException.from_exception(e)
    else:
        try:
            raise RuntimeError()
        except RuntimeError as e:
            result = traceback.TracebackException.from_exception(e)

    result.__cause__ = traceback_exception_deserialize(te["__cause__"]) if te["__cause__"] else None
    result.__context__ = traceback_exception_deserialize(te["__context__"]) if te["__context__"] else None
    result.stack = stack_summary_deserialize(te["stack"])

    # Handle exception type deserialization for different Python versions
    if "exc_type_str" in te and hasattr(result, "exc_type_str"):
        # Python 3.13+ approach - use the new string-based attributes
        # These are read-only in Python 3.14+, so we need to reconstruct the object
        # with the correct exception type
        if "exc_type" in te:
            # We have backward-compatible data, use it to get the actual type
            exc_type = exc_type_deserialize(te["exc_type"])
        else:
            # Try to reconstruct from string data
            module = te.get("exc_type_module", "builtins")
            qualname = te.get("exc_type_qualname", te["exc_type_str"])
            try:
                mod = importlib.import_module(module)
                exc_type = getattr(mod, qualname)
            except (ImportError, AttributeError):
                # Create a fake exception type
                exc_type = FakeException.create(module, qualname, f"<class '{module}.{qualname}'>")

        # Create a new TracebackException with the correct exc_type
        # This is necessary because exc_type is read-only in newer Python versions
        try:
            raise exc_type()
        except Exception as new_e:
            new_result = traceback.TracebackException.from_exception(new_e)
            result = _transfer_traceback_attributes(new_result, result, te)
    else:
        # Pre-Python 3.13 approach - directly set exc_type
        try:
            # Try to set exc_type directly (works in older Python versions)
            exc_type = exc_type_deserialize(te["exc_type"])
            result.exc_type = exc_type
        except AttributeError:
            # exc_type is read-only, need to work around this
            exc_type = exc_type_deserialize(te["exc_type"])
            try:
                raise exc_type()
            except Exception as new_e:
                new_result = traceback.TracebackException.from_exception(new_e)
                result = _transfer_traceback_attributes(new_result, result, te)

        # For the direct assignment case, we still need to set other attributes manually
        if hasattr(result, "exc_type"):  # Only if we successfully set exc_type directly
            # Set other attributes
            for name in _traceback_exception_attrs:
                if hasattr(result, name) and name in te:
                    setattr(result, name, te[name])

            # Handle syntax error attributes
            if te.get("syntax_error"):
                for name in _traceback_exception_syntax_attrs:
                    value = te["syntax_error"].get(name)
                    if value is not None and hasattr(result, name):
                        setattr(result, name, value)

    return result


def exc_type_serialize(exc_type: type) -> dict:
    return {
        "module": exc_type.__module__,
        "name": exc_type.__name__,
        "repr": repr(exc_type),
    }


def exc_type_deserialize(exc_type: dict):
    """
    returns either the type (if it exists locally) or a string
    """
    try:
        mod = importlib.import_module(exc_type["module"])
        return getattr(mod, exc_type["name"])
    except (ImportError, AttributeError):
        return FakeException.create(exc_type["module"], exc_type["name"], exc_type["repr"])


def stack_summary_serialize(stack_summary: traceback.StackSummary) -> list:
    return [frame_summary_serialize(frame_summary) for frame_summary in stack_summary]


def stack_summary_deserialize(stack_summary: list) -> traceback.StackSummary:
    lines = [frame_summary_deserialize(frame_summary) for frame_summary in stack_summary]
    return traceback.StackSummary.from_list(lines)


def frame_summary_serialize(frame_summary: traceback.FrameSummary) -> list:
    filename, lineno, name, line = tuple(frame_summary)
    return [filename, lineno, name, line, frame_summary.locals]


def frame_summary_deserialize(frame_summary: list) -> traceback.FrameSummary:
    filename, lineno, name, line, frame_locals = frame_summary
    fs = traceback.FrameSummary(filename, lineno, name, locals=frame_locals, line=line)
    return fs

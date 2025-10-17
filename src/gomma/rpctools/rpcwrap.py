"""
Helper tools for wrapping and unwrapping exceptions for RCP frameworks that don't, such as socketio.

Exceptions are wrapped into a special dict with a magic key, to be recognized as such.
This allows us to pass regular values through (without wrapping them) and only generate magic
exception objects when required.
"""

import functools
import inspect
import traceback

from .exc_tools import (
    RemoteException,
    traceback_exception_deserialize,
    traceback_exception_serialize,
)

# Helpers to serialize the TracebackException and related classes in the traceback module


def wrap_exception(exception: BaseException, reuse_wrap=True) -> dict:
    """
    Wrap an exception in a standard identifiable way using only jsonable data.
    If reuse_wrap is True, any previous wrapped error response in the exception
    is returned instead.  This is useful if an exception from remote is being passed
    on to a different remote.
    """
    if reuse_wrap and isinstance(exception, RemoteException):
        if getattr(exception, "wrapped_response", None):
            return exception.wrapped_response

    # return a magic dict with a key and version, and an exception member
    result = {
        "_wrapped_response_": "1.0",
        "success": False,
        "errors": [
            # list of error thingies
            {
                "exception": exception,
            },
        ],
    }
    return result


def wrap_result(result):
    """
    Wrap a result into a standard identifiable object
    """
    result = {
        "_wrapped_response_": "1.0",
        "success": True,
        "result": result,
    }
    return result


def wrapped_result_sanitize(wrapped):
    """
    Sanitize any errors in the result by converting them to serializable form.
    """
    if not wrapped["success"]:
        wrapped["errors"] = [error_sanitize(e) for e in wrapped["errors"]]
    return wrapped


def error_sanitize(error):
    exc = error.get("exception")
    if exc:
        # replace the exception with a serializable form
        tbe = traceback.TracebackException.from_exception(exc)
        strings = traceback.format_exception(type(exc), exc, exc.__traceback__)
        return {
            "python_traceback_exception": traceback_exception_serialize(tbe),
            "error_strings": strings,
        }
    return error


def unwrap_response(value):
    """
    Unwrap a potentially wrapped response and either return the response
    object or raise an error
    """
    if isinstance(value, dict):
        version = value.get("_wrapped_response_")
        if version is not None:
            # We identified a magic wrapping struct!
            if value["success"]:
                return value["result"]
            else:
                raise_from_errors(value["errors"], wrapped_response=value)

    # otherwise, this was just a plain, unwrapped, value
    return value


def is_wrapped_response(value):
    """
    Returns true if the argument is a wrapped exceptino
    """
    return isinstance(value, dict) and value.get("_wrapped_response_") is not None


def wrapped_response_success(value):
    return value["success"]


def raise_from_errors(errors, wrapped_response=None):
    """Raise an error from the wrapped errors.
    wrapped_response can be provided as the original wrapped response, to be re-used
    in case the resulting error is ever re-wrapped.
    """
    # support single error only for now.  There is at least one error
    err = errors[0]
    if "exception" in err:
        exception = err["exception"]
    elif "python_traceback_exception" in err:
        tbe = traceback_exception_deserialize(err["python_traceback_exception"])
        exception = RemoteException.FromTracebackException(tbe)
    else:
        exception = RemoteException.FromStrings(err["error_strings"])
    # store the original wrapped response in the exception object
    exception.wrapped_response = wrapped_response
    raise exception


# Wrapping remote calls.


def wrap_rpc_call(target, *args, **kwargs):
    result = target(*args, **kwargs)
    return unwrap_response(result)


async def async_wrap_rpc_call(target, *args, **kwargs):
    result = await target(*args, **kwargs)
    return unwrap_response(result)


def wrapped_rpc_call(func):
    """
    Decorator which applies the appropriate wrap function to the
    """
    if inspect.iscoroutinefunction(func):
        # Tecnically we don't need to have "wrapper" async, and await inside, but
        # could just pass the coroutine through.  But then the wrapper won't be marked
        # as a coroutinefunction.  Even functools.wraps() cannot fix that up.
        async def wrapper(*args, **kwargs):
            return await async_wrap_rpc_call(func, *args, **kwargs)

    else:

        def wrapper(*args, **kwargs):
            return wrap_rpc_call(func, *args, **kwargs)

    return functools.wraps(func)(wrapper)


# Wrapping a handler
# notice that these handlers do not catch BaseException, and so, if a base exception happens
# (e.g. a Task is cancelled) the caller cannot be notified of this.
# A different system must be used if we want to both, notify caller, _and_ re-raise error.
def wrap_rpc_handler(errorhandler, target, *args, **kwargs):
    try:
        result = target(*args, **kwargs)
        return wrap_result(result)
    except Exception as e:
        if errorhandler:
            errorhandler(e)
        return wrapped_result_sanitize(wrap_exception(e))


async def async_wrap_rpc_handler(errorhandler, target, *args, **kwargs):
    try:
        result = await target(*args, **kwargs)
        return wrap_result(result)
    except Exception as e:
        if errorhandler:
            errorhandler(e)
        return wrapped_result_sanitize(wrap_exception(e))


def wrapped_rpc_handler(errorhandler=None):
    """
    Decorator which applies the appropriate wrap function to the rpc handler
    """

    def helper(func):
        if inspect.iscoroutinefunction(func):
            # Tecnically we don't need to have "wrapper" async, and await inside, but
            # could just pass the coroutine through.  But then the wrapper won't be marked
            # as a coroutinefunction.  Even functools.wraps() cannot fix that up.
            async def wrapper(*args, **kwargs):
                return await async_wrap_rpc_handler(errorhandler, func, *args, **kwargs)

        else:

            def wrapper(*args, **kwargs):
                return wrap_rpc_handler(errorhandler, func, *args, **kwargs)

        return functools.wraps(func)(wrapper)

    return helper

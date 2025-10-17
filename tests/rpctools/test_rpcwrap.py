import traceback
from unittest.mock import Mock

import pytest

from gomma.rpctools import rpcwrap


def problemhandler(*args):
    try:
        return problemhandler2(*args)
    except ZeroDivisionError as e:
        raise RuntimeError("bad timing") from e


def problemhandler2(*args):
    1 / 0
    return "notreached"


def test_wrap():
    try:
        problemhandler()
    except Exception as e:
        wrapped = rpcwrap.wrap_exception(e)

    assert rpcwrap.is_wrapped_response(wrapped)
    assert not rpcwrap.wrapped_response_success(wrapped)
    exception = wrapped["errors"]
    assert exception


def test_wrap_success():
    wrapped = rpcwrap.wrap_result("hello dolly")

    assert rpcwrap.is_wrapped_response(wrapped)
    assert rpcwrap.wrapped_response_success(wrapped)
    assert rpcwrap.unwrap_response(wrapped) == "hello dolly"


def test_wrap_handler():
    logger = Mock()
    wrapped = rpcwrap.wrap_rpc_handler(logger, problemhandler)
    logger.assert_called()

    assert rpcwrap.is_wrapped_response(wrapped)
    assert not rpcwrap.wrapped_response_success(wrapped)
    errors = wrapped["errors"]
    assert errors


def test_wrap_handler_decorator():
    errorhandler = Mock()

    @rpcwrap.wrapped_rpc_handler(errorhandler)
    def handler():
        return problemhandler()

    wrapped = handler()
    errorhandler.assert_called()

    assert rpcwrap.is_wrapped_response(wrapped)
    assert not rpcwrap.wrapped_response_success(wrapped)
    exception = wrapped["errors"]
    assert exception


def test_both_decorators():
    errorhandler = Mock()

    @rpcwrap.wrapped_rpc_handler(errorhandler)
    def handler():
        return problemhandler()

    @rpcwrap.wrapped_rpc_call
    def call():
        return handler()

    with pytest.raises(rpcwrap.RemoteException):
        call()


def test_raise_from_wrapped():
    errorhandler = Mock()
    wrapped = rpcwrap.wrap_rpc_handler(errorhandler, problemhandler)
    errorhandler.assert_called()
    assert rpcwrap.is_wrapped_response(wrapped)
    assert not rpcwrap.wrapped_response_success(wrapped)

    with pytest.raises(rpcwrap.RemoteException):
        rpcwrap.unwrap_response(wrapped)


def test_remote_exception():
    errorhandler = Mock()
    wrapped = rpcwrap.wrap_rpc_handler(errorhandler, problemhandler)
    errorhandler.assert_called()
    try:
        rpcwrap.unwrap_response(wrapped)
    except rpcwrap.RemoteException as e:
        exc = e

    f = traceback.format_exception(type(exc), exc, exc.__traceback__)
    assert any("bad timing" in s for s in f)


def test_unsanitized():
    try:
        problemhandler()
    except Exception as exc:
        wrapped = rpcwrap.wrap_exception(exc)
    assert rpcwrap.is_wrapped_response(wrapped)
    assert not rpcwrap.wrapped_response_success(wrapped)

    with pytest.raises(RuntimeError):
        rpcwrap.unwrap_response(wrapped)


def test_rewrap_raise_from_wrapped():
    """
    Test that when wrapping an exception that was raised by unwrapping an original exception,
    we can just get the original wrap
    """

    # create a wrapped exception
    errorhandler = Mock()
    wrapped = rpcwrap.wrap_rpc_handler(errorhandler, problemhandler)
    errorhandler.assert_called()
    assert rpcwrap.is_wrapped_response(wrapped)

    # raise from wrapped
    with pytest.raises(rpcwrap.RemoteException) as excinfo:
        rpcwrap.unwrap_response(wrapped)

    # we now have an error that we wish to wrap
    wrapped2 = rpcwrap.wrap_exception(excinfo.value)
    assert wrapped2 == wrapped

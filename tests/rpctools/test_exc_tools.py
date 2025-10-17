import traceback
import warnings

from gomma.rpctools import exc_tools


def test_dynamic_exception():
    """Test that an exception type is dynamically crated"""

    # create an exception
    try:
        1 / 0
    except Exception as err:
        tbe = traceback.TracebackException.from_exception(err)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            print(dir(tbe.exc_type))

    serial = exc_tools.traceback_exception_serialize(tbe)
    assert serial["type"] == "TracebackException:1.0"

    exc_type = serial["exc_type"]
    assert exc_type["module"] == "builtins"
    assert exc_type["name"] == "ZeroDivisionError"

    # modify the exception name
    exc_type["module"] = "lumber"
    exc_type["name"] = "LumberError"

    # deserialize again
    tbe = exc_tools.traceback_exception_deserialize(serial)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        exc_type = tbe.exc_type

    assert issubclass(exc_type, Exception)
    assert isinstance(exc_type(), Exception)
    assert exc_type.__name__ == "LumberError"
    assert exc_type.__qualname__ == "LumberError"
    assert exc_type.__module__ == "lumber"
    assert repr(exc_type()) == "LumberError()"


def test_syntax_error_serialization():
    """Test that SyntaxError serialization and deserialization preserves special attributes"""
    
    # Create a SyntaxError with typical attributes
    try:
        compile("invalid syntax here $$", "test_file.py", "exec")
    except SyntaxError as err:
        tbe = traceback.TracebackException.from_exception(err)

    # Serialize
    serial = exc_tools.traceback_exception_serialize(tbe)
    assert serial["type"] == "TracebackException:1.0"
    
    # Should have syntax error data
    assert "syntax_error" in serial
    assert serial["syntax_error"] is not None
    syntax_data = serial["syntax_error"]
    
    # Verify syntax error attributes are preserved
    assert syntax_data["filename"] == "test_file.py"
    assert syntax_data["lineno"] == "1"  # Note: stored as string in some Python versions
    assert syntax_data["msg"] == "invalid syntax"
    assert "offset" in syntax_data
    assert "text" in syntax_data

    # Deserialize
    deserialized = exc_tools.traceback_exception_deserialize(serial)
    
    # Verify the deserialized exception preserves syntax error attributes
    assert hasattr(deserialized, 'filename')
    assert hasattr(deserialized, 'lineno')
    assert hasattr(deserialized, 'msg')
    assert hasattr(deserialized, 'offset')
    assert hasattr(deserialized, 'text')
    
    assert deserialized.filename == "test_file.py"
    assert deserialized.lineno == 1 or deserialized.lineno == "1"  # Handle both int and string
    assert deserialized.msg == "invalid syntax"
    
    # Verify that the exception type is still SyntaxError (with warnings suppressed)
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        assert issubclass(deserialized.exc_type, SyntaxError)

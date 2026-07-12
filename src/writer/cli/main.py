"""兼容层：把 ``cli/main.py`` 拆为 ``repl`` / ``commands`` / ``_init_backend`` 后,
保留原导入路径 ``from writer.cli.main import X`` 不破坏现有调用方
(tests/test_cli.py / tests/test_new_command.py / __main__.py /
scripts/pyinstaller_entrypoint.py / pyproject.toml 脚本入口)。

最终会移除；现阶段作为 shim，等所有调用方迁到新模块后再删。
"""
from writer.cli._init_backend import init_project  # noqa: F401
from writer.cli.commands import (  # noqa: F401
    app,
    doctor,
    main,
    new_project_cmd,
    version_callback,
)
from writer.cli.repl import (  # noqa: F401
    EXIT_COMMANDS,
    HELP_COMMANDS,
    NO_HISTORY,
    REPL_COMMANDS,
    REPL_PROMPT,
    STATIC_REPL_COMMANDS,
    _read_line,
    _resolve_history_file,
    _run_engine,
    build_prompt_session,
    build_repl_commands,
    console,
    handle_repl_input,
    print_repl_help,
    print_welcome,
    run_repl,
)

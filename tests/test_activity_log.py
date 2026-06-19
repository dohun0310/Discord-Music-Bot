from app.activity_log import command_context, format_command_args


class _Namespace:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _Named:
    def __init__(self, name):
        self.name = name


class _Interaction:
    def __init__(self, *, guild=None, command=None, user=None, namespace=None):
        self.guild = guild
        self.command = command
        self.user = user
        self.namespace = namespace


def test_format_args_empty():
    assert format_command_args(_Interaction(namespace=_Namespace())) == ""


def test_format_args_with_values():
    interaction = _Interaction(namespace=_Namespace(query="아이유 밤편지", volume=120))
    out = format_command_args(interaction)
    assert out.startswith(" (") and out.endswith(")")
    assert "query=" in out and "아이유 밤편지" in out
    assert "volume=120" in out


def test_command_context_guild_user_command():
    interaction = _Interaction(
        guild=_Named("내 서버"), command=_Named("재생"), user=_Named("도훈")
    )
    assert command_context(interaction) == ("내 서버", "재생", "도훈")


def test_command_context_dm_and_unknown_command():
    interaction = _Interaction(guild=None, command=None, user=_Named("도훈"))
    guild, name, user = command_context(interaction)
    assert guild == "DM"
    assert name == "알 수 없음"
    assert user == "도훈"

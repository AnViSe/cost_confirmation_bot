from operator import attrgetter, itemgetter
from typing import Any, Union

from aiogram.types import CallbackQuery, Message
from aiogram.utils.text_decorations import html_decoration as fmt
from aiogram_dialog import Data, Dialog, DialogManager, Window
from aiogram_dialog.manager.protocols import ManagedDialogAdapterProto
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import (
    Button,
    Cancel,
    Column,
    Multiselect,
    Next,
    ScrollingGroup,
    Select,
    SwitchTo,
)
from aiogram_dialog.widgets.managed import ManagedWidgetAdapter
from aiogram_dialog.widgets.text import Const, Format, Multi

from app.domain.access_levels.interfaces.uow import IAccessLevelUoW
from app.domain.access_levels.usecases.access_levels import (
    GetAccessLevels,
    GetUserAccessLevels,
)
from app.domain.user.dto.user import PatchUserData, UserPatch
from app.domain.user.exceptions.user import UserNotExists
from app.domain.user.interfaces.uow import IUserUoW
from app.domain.user.usecases.user import GetUser, PatchUser
from app.infrastructure.database.models import TelegramUserEntry
from app.tgbot import states
from app.tgbot.constants import (
    ACCESS_LEVELS,
    ALL_ACCESS_LEVELS,
    FIELD,
    OLD_USER_ID,
    USER,
    USER_ID,
    USER_NAME,
    USERS,
)
from app.tgbot.handlers.admin.user.common import (
    copy_start_data_to_context,
    get_user_data,
    get_users,
    user_adding_process,
)
from app.tgbot.handlers.dialogs.common import enable_send_mode, get_result

IUserAccessLevelUoW = Union[IUserUoW, IAccessLevelUoW]


async def save_user_id(
    query: CallbackQuery,
    select: ManagedWidgetAdapter[Select],
    manager: DialogManager,
    item_id: str,
):
    manager.current_context().dialog_data[OLD_USER_ID] = item_id
    await manager.dialog().next()
    await query.answer()


async def get_old_user(dialog_manager: DialogManager, uow: IUserUoW, **kwargs):
    user_id = dialog_manager.current_context().dialog_data[OLD_USER_ID]
    try:
        user = await GetUser(uow)(int(user_id))
    except UserNotExists:  # ToDo check if need
        user = None
    return {USER: user}


async def request_id(
    message: Message, dialog: ManagedDialogAdapterProto, manager: DialogManager
):
    if not message.text.isdigit():
        await message.answer("User id value must be digit")
        return

    await manager.done({USER_ID: message.text})


async def request_name(
    message: Message, dialog: ManagedDialogAdapterProto, manager: DialogManager
):
    await manager.done({USER_NAME: message.text})


COLUMN_STATES = {
    TelegramUserEntry.id.name: states.user_db.EditUserId.request,
    TelegramUserEntry.name.name: states.user_db.EditUserName.request,
    TelegramUserEntry.access_levels.key: states.user_db.EditAccessLevel.request,
}


async def on_field_selected(
    query: CallbackQuery,
    select: ManagedWidgetAdapter[Select],
    manager: DialogManager,
    item_id: str,
):
    await manager.start(
        state=COLUMN_STATES[item_id],
        data=manager.current_context().dialog_data.copy(),
    )
    await query.answer()


async def get_user_edit_data(
    dialog_manager: DialogManager, uow: IUserAccessLevelUoW, **kwargs
):
    user_id = dialog_manager.current_context().dialog_data[OLD_USER_ID]

    user = await GetUser(uow)(int(user_id))
    fields = TelegramUserEntry.__table__.columns.keys()
    fields.append(TelegramUserEntry.access_levels.key)
    fields = [(f, f) for f in fields]

    dialog_manager.current_context().dialog_data[USER] = user.json()

    user_data = await get_user_data(dialog_manager, uow)

    return {USER: user, "fields": fields} | user_data


async def process_result(start_data: Data, result: Any, dialog_manager: DialogManager):
    if result.get(USER_ID):
        dialog_manager.current_context().dialog_data[USER_ID] = result[USER_ID]
    if result.get(USER_NAME):
        dialog_manager.current_context().dialog_data[USER_NAME] = result[USER_NAME]
    if result.get(ACCESS_LEVELS):
        dialog_manager.current_context().dialog_data[ACCESS_LEVELS] = result[
            ACCESS_LEVELS
        ]


async def get_access_levels(
    dialog_manager: DialogManager, uow: IUserAccessLevelUoW, **kwargs
):

    user_id = dialog_manager.current_context().dialog_data[OLD_USER_ID]
    access_levels = await GetAccessLevels(uow)()

    init_check = dialog_manager.current_context().dialog_data.get("init_check")
    if init_check is None:
        user_access_levels = await GetUserAccessLevels(uow)(int(user_id))
        checked = dialog_manager.current_context().widget_data.setdefault(
            ACCESS_LEVELS, []
        )
        checked.extend(map(str, (level.id for level in user_access_levels)))
        dialog_manager.current_context().dialog_data["init_check"] = True

    access_levels = {
        ALL_ACCESS_LEVELS: [(level.name.name, level.id) for level in access_levels],
    }
    user_data = await get_old_user(dialog_manager, uow)

    return user_data | access_levels


async def save_access_levels(
    query: CallbackQuery, button, dialog_manager: DialogManager, **kwargs
):
    access_levels: Multiselect = dialog_manager.dialog().find(ACCESS_LEVELS)
    selected_levels = access_levels.get_checked(dialog_manager)

    if not selected_levels:
        await query.answer("select at least one level")
        return

    await dialog_manager.done({ACCESS_LEVELS: selected_levels})


async def save_edited_user(
    query: CallbackQuery, button, dialog_manager: DialogManager, **kwargs
):
    uow: IUserUoW = dialog_manager.data.get("uow")
    data = dialog_manager.current_context().dialog_data

    user = UserPatch(
        id=data[OLD_USER_ID],
        user_data=PatchUserData(
            id=data.get(USER_ID),
            name=data.get(USER_NAME),
            access_levels=data.get(ACCESS_LEVELS),
        ),
    )

    new_user = await PatchUser(uow=uow)(user)
    levels_names = ", ".join((level.name.name for level in new_user.access_levels))

    result = fmt.quote(
        f"User {data[OLD_USER_ID]} edited\n"
        f"id:           {new_user.id}\n"
        f"name:         {new_user.name}\n"
        f"access level: {levels_names}\n"
    )
    data["result"] = result

    await dialog_manager.dialog().next()
    await query.answer()


user_id_dialog = Dialog(
    Window(
        Format("Input new id for {user.id}"),
        MessageInput(request_id),
        getter=get_old_user,
        state=states.user_db.EditUserId.request,
    ),
    on_start=copy_start_data_to_context,
)

user_name_dialog = Dialog(
    Window(
        Format("Input new name for {user.id}"),
        MessageInput(request_name),
        getter=get_old_user,
        state=states.user_db.EditUserName.request,
    ),
    on_start=copy_start_data_to_context,
)

user_access_levels_dialog = Dialog(
    Window(
        Format("Select access levels for {user.id}"),
        Column(
            Multiselect(
                Format("✓ {item[0]}"),
                Format("{item[0]}"),
                id=ACCESS_LEVELS,
                item_id_getter=itemgetter(1),
                items=ALL_ACCESS_LEVELS,
            )
        ),
        Button(
            Const("Save"),
            id="save_access_levels",
            on_click=save_access_levels,
        ),
        getter=get_access_levels,
        state=states.user_db.EditAccessLevel.request,
    ),
    on_start=copy_start_data_to_context,
)


edit_user_dialog = Dialog(
    Window(
        Const("Select user for editing:"),
        ScrollingGroup(
            Select(
                Format("{item.name} {item.id}"),
                id=OLD_USER_ID,
                item_id_getter=attrgetter("id"),
                items="users",
                on_click=save_user_id,
            ),
            id="user_scrolling",
            width=1,
            height=5,
        ),
        Cancel(),
        getter=get_users,
        state=states.user_db.EditUser.select_user,
        preview_add_transitions=[Next()],
    ),
    Window(
        Multi(
            Format("Selected user: {user.id}\nName: {user.name}\n\n"),
            user_adding_process,
        ),
        Column(
            Select(
                Format("{item[0]}"),
                id=FIELD,
                item_id_getter=itemgetter(1),
                items="fields",
                on_click=on_field_selected,
            ),
            Button(Const("Save"), id="save", on_click=save_edited_user),
            Cancel(),
        ),
        getter=get_user_edit_data,
        state=states.user_db.EditUser.select_field,
        parse_mode="HTML",
        preview_add_transitions=[
            SwitchTo(Const(""), id="", state=states.user_db.EditUserId.request),
            SwitchTo(Const(""), id="", state=states.user_db.EditUserName.request),
            SwitchTo(Const(""), id="", state=states.user_db.EditAccessLevel.request),
            Next(),
        ],
    ),
    Window(
        Format("{result}"),
        Cancel(Const("Close"), on_click=enable_send_mode),
        getter=get_result,
        state=states.user_db.EditUser.result,
        parse_mode="HTML",
    ),
    on_process_result=process_result,
)

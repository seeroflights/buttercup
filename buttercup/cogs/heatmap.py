import io
from datetime import datetime
from typing import Optional

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from blossom_wrapper import BlossomAPI
from discord import File
from discord.ext.commands import Cog
from discord_slash import SlashContext, cog_ext
from discord_slash.utils.manage_commands import create_option

from buttercup.bot import ButtercupBot
from buttercup.cogs.helpers import (
    BlossomException,
    BlossomUser,
    extract_utc_offset,
    get_duration_str,
    get_initial_username,
    get_user,
    get_user_id,
    get_username,
    parse_time_constraints,
    utc_offset_to_str,
)
from buttercup.strings import translation

i18n = translation()


def create_file_from_heatmap(
    heatmap: pd.DataFrame, user: Optional[BlossomUser], utc_offset: int = 0
) -> File:
    """Create a Discord file containing the heatmap table."""
    days = i18n["heatmap"]["days"]
    hours = ["{:02d}".format(hour) for hour in range(0, 24)]

    # The built in formatting for the heatmap doesn't allow displaying floats as ints
    # And we have to use floats because empty entries are NaN
    # So we have to manually provide the annotations
    annotations = heatmap.apply(
        lambda series: series.apply(lambda value: f"{value:0.0f}")
    )

    fig, ax = plt.subplots()
    fig.set_size_inches(9, 3.44)

    sns.heatmap(
        heatmap,
        ax=ax,
        annot=annotations,
        fmt="s",
        cbar=False,
        square=True,
        xticklabels=hours,
        yticklabels=days,
    )

    timezone = utc_offset_to_str(utc_offset)

    plt.title(i18n["heatmap"]["plot_title"].format(user=get_username(user)))
    plt.xlabel(i18n["heatmap"]["plot_xlabel"].format(timezone=timezone))
    plt.ylabel(i18n["heatmap"]["plot_ylabel"])

    fig.tight_layout()
    heatmap_table = io.BytesIO()
    plt.savefig(heatmap_table, format="png")
    heatmap_table.seek(0)
    plt.close(fig)

    return File(heatmap_table, "heatmap_table.png")


class Heatmap(Cog):
    def __init__(self, bot: ButtercupBot, blossom_api: BlossomAPI) -> None:
        """Initialize the Heatmap cog."""
        self.bot = bot
        self.blossom_api = blossom_api

    @cog_ext.cog_slash(
        name="heatmap",
        description="Display the activity heatmap for the given user.",
        options=[
            create_option(
                name="username",
                description="The user to get the heatmap for.",
                option_type=3,
                required=False,
            ),
            create_option(
                name="after",
                description="The start date for the heatmap data.",
                option_type=3,
                required=False,
            ),
            create_option(
                name="before",
                description="The end date for the heatmap data.",
                option_type=3,
                required=False,
            ),
        ],
    )
    async def _heatmap(
        self,
        ctx: SlashContext,
        username: Optional[str] = "me",
        after: Optional[str] = None,
        before: Optional[str] = None,
    ) -> None:
        """Generate a heatmap for the given user."""
        start = datetime.now()

        after_time, before_time, time_str = parse_time_constraints(after, before)

        msg = await ctx.send(
            i18n["heatmap"]["getting_heatmap"].format(
                user=get_initial_username(username, ctx), time_str=time_str
            )
        )

        utc_offset = extract_utc_offset(ctx.author.display_name)

        from_str = after_time.isoformat() if after_time else None
        until_str = before_time.isoformat() if before_time else None

        user = get_user(username, ctx, self.blossom_api)

        heatmap_response = self.blossom_api.get(
            "submission/heatmap/",
            params={
                "completed_by": get_user_id(user),
                "utc_offset": utc_offset,
                "complete_time__gte": from_str,
                "complete_time__lte": until_str,
            },
        )
        if heatmap_response.status_code != 200:
            raise BlossomException(heatmap_response)

        data = heatmap_response.json()

        day_index = pd.Index(range(1, 8))
        hour_index = pd.Index(range(0, 24))

        heatmap = (
            # Create a data frame from the data
            pd.DataFrame.from_records(data, columns=["day", "hour", "count"])
            # Convert it into a table with the days as rows and hours as columns
            .pivot(index="day", columns="hour", values="count")
            # Add the missing days and hours
            .reindex(index=day_index, columns=hour_index)
        )

        heatmap_table = create_file_from_heatmap(heatmap, user, utc_offset)

        await msg.edit(
            content=i18n["heatmap"]["response_message"].format(
                user=get_username(user),
                time_str=time_str,
                duration=get_duration_str(start),
            ),
            file=heatmap_table,
        )


def setup(bot: ButtercupBot) -> None:
    """Set up the Heatmap cog."""
    # Initialize blossom api
    cog_config = bot.config["Blossom"]
    email = cog_config.get("email")
    password = cog_config.get("password")
    api_key = cog_config.get("api_key")
    blossom_api = BlossomAPI(email=email, password=password, api_key=api_key)

    bot.add_cog(Heatmap(bot=bot, blossom_api=blossom_api))


def teardown(bot: ButtercupBot) -> None:
    """Unload the Heatmap cog."""
    bot.remove_cog("Heatmap")

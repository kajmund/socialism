"""Swedish OASIS environment prompts (inspired by inspiration/riksdag2026).

Monkeypatches camel-oasis SocialEnvironment templates for the current process.
Call only when the oasis extra is installed.
"""

from __future__ import annotations

import json
from string import Template


def apply_swedish_social_environment_prompts() -> None:
    """Replace English SocialEnvironment feed prompts with Swedish guidance."""
    from oasis.social_agent import agent_environment as mod

    se = mod.SocialEnvironment
    se.followers_env_template = Template("Jag har $num_followers följare.")
    se.follows_env_template = Template("Jag har $num_follows följningar.")
    se.posts_env_template = Template(
        "Efter uppdatering ser du följande inlägg: $posts"
    )
    se.groups_env_template = Template(
        "Det finns gruppkanaler: $all_groups\n"
        "Du är redan med i vissa grupper: $joined_groups\n"
        "Meddelanden: $messages\n"
        "Du kan gå med i grupper du vill, lämna grupper du är i och skriva "
        "till grupper du redan tillhör."
    )
    se.env_template = Template(
        "$groups_env\n"
        "$posts_env\n"
        "Välj den åtgärd som bäst speglar din bakgrund och vad du ser i flödet. "
        "Du behöver inte göra något om inget engagerar dig. "
        "Gilla (like) bara när du faktiskt stöder inlägget eller håller med. "
        "Ogilla (dislike) när du tar avstånd. "
        "Om du kritiserar eller sarkastiskt kommenterar ett inlägg: gilla det inte. "
        "Kommentera, följ, dela eller gör inget om det passar bättre. "
        "Om du skriver text: variera formulering; upprepa inte samma inledning "
        "eller avslutning varje gång."
    )

    async def get_posts_env_sv(self):
        posts = await self.action.refresh()
        if posts["success"]:
            posts_env = json.dumps(posts["posts"], indent=4)
            posts_env = self.posts_env_template.substitute(posts=posts_env)
        else:
            posts_env = "Efter uppdatering finns inga inlägg att visa."
        return posts_env

    async def get_group_env_sv(self):
        groups = await self.action.listen_from_group()
        if groups["success"]:
            all_groups = json.dumps(groups["all_groups"])
            joined_groups = json.dumps(groups["joined_groups"])
            messages = json.dumps(groups["messages"])
            groups_env = self.groups_env_template.substitute(
                all_groups=all_groups,
                joined_groups=joined_groups,
                messages=messages,
            )
        else:
            groups_env = "Inga gruppchattar."
        return groups_env

    async def to_text_prompt_sv(
        self,
        include_posts: bool = True,
        include_followers: bool = True,
        include_follows: bool = True,
    ) -> str:
        followers_env = (
            await self.get_followers_env()
            if include_follows
            else "Inga följare listade."
        )
        follows_env = (
            await self.get_follows_env()
            if include_followers
            else "Inga följningar listade."
        )
        posts_env = await self.get_posts_env() if include_posts else ""

        return self.env_template.substitute(
            followers_env=followers_env,
            follows_env=follows_env,
            posts_env=posts_env,
            groups_env=await self.get_group_env(),
        )

    se.get_posts_env = get_posts_env_sv
    se.get_group_env = get_group_env_sv
    se.to_text_prompt = to_text_prompt_sv

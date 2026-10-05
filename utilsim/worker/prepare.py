"""From the Studio's inputs to a portable job: the recipe every district runs, numbered as a revision."""
from __future__ import annotations

import uuid

from fastapi import HTTPException


async def body(request, limit=2_000_000):
    """A request's JSON object, bounded (job metadata is small; full archives never travel)."""
    import orjson

    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > limit:
            raise HTTPException(413, 'The request is too large.')
    try:
        value = orjson.loads(raw)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except ValueError as exc:
        raise HTTPException(422, 'Expected a JSON object.') from exc


def pattern_seed(model_id):
    """A simulation's own seed for its sporadic episodes' days (as the Studio's local-year.js patternSeed)."""
    return ('local:' + str(model_id))[:64]


def seeded_episodes(proposal, model_id):
    """The proposal with each sporadic episode's pattern given the simulation's seed when it has none. A job's
    districts are separate towns with their own run seeds, so without it each district would strike different days."""
    episodes = proposal.get('episodes') if isinstance(proposal, dict) else None
    if not isinstance(episodes, list):
        return proposal

    def seeded(ep):
        p = ep.get('pattern') if isinstance(ep, dict) else None
        if not isinstance(p, dict) or p.get('seed'):
            return ep
        return {**ep, 'pattern': {**p, 'seed': pattern_seed(model_id)}}
    return {**proposal, 'episodes': [seeded(ep) for ep in episodes]}


def prepare_recipe(value):
    """``{proposal, modelId, staffing, chunkSize?}`` → a checked recipe (ValueError / ValidationError when not)."""
    from api._agent_config import Proposal, preset_config, validate_proposal
    from utilsim.config.presets import deep_merge
    from utilsim.worker.contracts import Recipe

    proposal = Proposal.model_validate(seeded_episodes(value['proposal'], value['modelId']))
    validated = validate_proposal(proposal)
    config = deep_merge(preset_config(proposal.preset).model_dump(mode='json'), proposal.townOverrides)
    from utilsim.worker.workspace import actions_for, scopes
    actions = value.get('actions', [])
    if any(len(scopes(a)) != 1 for a in actions):
        raise ValueError('Each decision must identify a record in this utility.')
    grouped = {district: actions_for(actions, district) for district in sorted(scopes(actions))}
    return Recipe(name=proposal.name, modelId=value['modelId'], homes=proposal.totalHomes or validated['homes'],
                  chunkSize=value.get('chunkSize', 10000), staffing=value.get('staffing', 'independent-districts'),
                  config=config, proposal={**proposal.model_dump(by_alias=True), 'townRef': validated['townRef']},
                  request={'settings': proposal.settings, 'episodes': validated['episodes'],
                           'seed': proposal.seed or None, 'asOf': proposal.asOf,
                           **({'actionsByDistrict': grouped} if grouped else {})}).model_dump()


def prepare_job(value, revision):
    """A checked job file for the next revision of a simulation."""
    from utilsim.worker.contracts import JobFile, check_job, recipe_key

    recipe = prepare_recipe(value)
    job = JobFile(jobId=uuid.uuid4().hex, revision=int(revision), recipeKey=recipe_key(recipe), recipe=recipe).model_dump()
    return check_job(job)

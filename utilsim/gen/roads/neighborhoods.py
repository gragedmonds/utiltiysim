"""Connected neighborhood loops and interior blocks, opt-in neighborhood-streets/1.

Geometry remains synthetic. Existing arterials/collectors retain their role;
local access links connect each new loop before any interior subdivision.
"""
import math

import numpy as np
from shapely.geometry import LineString, Point
from shapely.ops import nearest_points, split

from utilsim.core.rng import stage_rng
from utilsim.gen.roads.model import LOCAL, ROW_WIDTH, RoadLine
from utilsim.gen.roads.synthetic import _extend, _long_axis, _polys_of

VERSION = "neighborhood-streets/1"


def _ordered(polygons):
    return sorted(polygons, key=lambda p: (round(p.centroid.x, 2), round(p.centroid.y, 2)))


def _cross_angle(line, distance, direction):
    """Angle to the local street tangent, rejecting almost-parallel joins."""
    a = np.asarray(line.interpolate(max(0, distance-3)).coords[0])
    b = np.asarray(line.interpolate(min(line.length, distance+3)).coords[0])
    tangent = b-a
    norm = np.linalg.norm(tangent)*np.linalg.norm(direction)
    if norm < 1e-8:
        return 0
    cosine = np.clip(abs(np.dot(tangent, direction))/norm, 0, 1)
    return math.degrees(math.acos(cosine))


def _access(inner, block, anchor, setback, junctions):
    """Pick two separated access points. Never attach a neighborhood to the map frame."""
    ring = LineString(inner.exterior.coords)
    candidates = []
    for fraction in np.linspace(0, 1, 33)[:-1]:
        p = ring.interpolate(fraction, normalized=True)
        q = nearest_points(p, anchor)[1]
        if any(q.distance(old) < 30 for old in junctions):
            continue
        link = LineString([p, q])
        if not 15 < link.length < setback*2.5 or not block.buffer(.1).covers(link):
            continue
        if link.intersects(inner.buffer(-.1)):
            continue
        direction = np.asarray(q.coords[0])-np.asarray(p.coords[0])
        if _cross_angle(ring, ring.project(p), direction) < 55:
            continue
        # Recover the containing anchor segment to check the main-road junction.
        pieces = list(anchor.geoms) if hasattr(anchor, 'geoms') else [anchor]
        nearest = min(pieces, key=lambda road: road.distance(q))
        if _cross_angle(nearest, nearest.project(q), direction) < 55:
            continue
        candidates.append(link)
    candidates.sort(key=lambda line: (round(line.length, 3), tuple(line.coords[0])))
    chosen = []
    for link in candidates:
        if any(Point(link.coords[0]).distance(Point(old.coords[0])) < 75 or
               Point(link.coords[-1]).distance(Point(old.coords[-1])) < 75 or link.crosses(old)
               for old in chosen):
            continue
        chosen.append(link)
        if len(chosen) == 2:
            return chosen
    return []


def local_lines(seed, blocks, era, lot_depth_by_era, anchor):
    """Local roads with two access routes and deterministic connected block cuts."""
    roads, templates = [], []
    main_junctions = []
    for bi, block in enumerate(blocks):
        era_index = int(era.era_at(np.asarray(block.representative_point().coords))[0])
        templates.append(era_index)
        depth = lot_depth_by_era[era_index]
        setback = 2*depth + ROW_WIDTH[LOCAL]
        interiors = _ordered(_polys_of(block.buffer(-setback, join_style=2)))
        rng = stage_rng(seed, VERSION, str(bi))
        for ii, inner in enumerate(interiors):
            _, _, short = _long_axis(inner)
            if inner.area < 4500 or short < 55:
                continue  # Main-road frontage remains; no unusably thin local loop.
            access = _access(inner, block, anchor, setback, main_junctions)
            if not access:
                continue  # Do not invent an isolated local network.
            prefix = f"nb-{bi}-{ii}"
            main_junctions.extend(Point(link.coords[-1]) for link in access)
            local_junctions = [np.asarray(link.coords[0]) for link in access]
            roads.append(RoadLine(np.asarray(inner.exterior.coords), LOCAL, source_id=prefix+'-loop'))
            for ai, link in enumerate(access):
                roads.append(RoadLine(_extend(np.asarray(link.coords), .6), LOCAL, source_id=f'{prefix}-access-{ai}'))

            def subdivide(poly, level=0, *, target=(190, 220, 250)[era_index],
                          setback=setback, rng=rng, prefix=prefix, junctions=local_junctions):
                angle, long, short = _long_axis(poly)
                if level >= 8 or short < 55 or (long <= target and short <= setback*1.3):
                    return
                direction = np.array([math.cos(angle), math.sin(angle)])
                normal = np.array([-direction[1], direction[0]])
                center = np.asarray(poly.minimum_rotated_rectangle.centroid.coords[0])
                for fraction in (float(rng.uniform(.46, .54)), .4, .6):
                    mid = center + direction*(fraction-.5)*long
                    chord = LineString([mid-normal*(long+short), mid+normal*(long+short)]).intersection(poly)
                    if chord.geom_type != 'LineString' or chord.length < 55:
                        continue
                    points = np.asarray(chord.coords)
                    if any(np.linalg.norm(p-old) < 25 for p in (points[0], points[-1]) for old in junctions):
                        continue
                    boundary = LineString(poly.exterior.coords)
                    if any(_cross_angle(boundary, boundary.project(Point(p)), points[-1]-points[0]) < 55
                           for p in (points[0], points[-1])):
                        continue
                    # Keep new T-junctions clear of existing corners/intersections.
                    vertices = np.asarray(poly.exterior.coords)[:-1]
                    before = vertices-np.roll(vertices, 1, axis=0)
                    after = np.roll(vertices, -1, axis=0)-vertices
                    cosine = np.sum(before*after, axis=1)/(np.linalg.norm(before, axis=1)*np.linalg.norm(after, axis=1))
                    corners = vertices[cosine < math.cos(math.radians(20))]
                    if any(np.min(np.linalg.norm(corners-p, axis=1)) < 25 for p in (points[0], points[-1])):
                        continue
                    halves = _ordered(_polys_of(split(poly, LineString(_extend(points, 2)))))
                    if len(halves) != 2 or min(p.area for p in halves) < 2500:
                        continue
                    roads.append(RoadLine(_extend(points, .6), LOCAL, source_id=f'{prefix}-block-{len(roads)}'))
                    junctions.extend((points[0], points[-1]))
                    for half in halves:
                        subdivide(half, level+1)
                    break

            subdivide(inner)
    return roads, [], templates

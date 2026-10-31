"""Deterministic left-to-right auto-layout for process specs."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from models.schemas import ProcessSpec

COLUMN_WIDTH = 170
ROW_HEIGHT = 130
LOOP_PADDING = 40
POOL_LABEL = 30
LANE_LABEL = 30
ORIGIN = 40
CONTENT_MARGIN = 40
TASK_SIZE = (100, 80)
EVENT_SIZE = (36, 36)
GATEWAY_SIZE = (50, 50)

Point = tuple[float, float]


@dataclass
class Bounds:
    x: float
    y: float
    width: float
    height: float

    @property
    def cx(self) -> float:
        return self.x + self.width / 2

    @property
    def cy(self) -> float:
        return self.y + self.height / 2

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height


@dataclass
class Layout:
    shapes: dict[str, Bounds] = field(default_factory=dict)
    shape_labels: dict[str, Bounds] = field(default_factory=dict)
    edges: list[list[Point]] = field(default_factory=list)
    labels: list[Bounds | None] = field(default_factory=list)
    lanes: dict[str, Bounds] = field(default_factory=dict)
    pool: Bounds | None = None


def _size(node_type: str) -> tuple[int, int]:
    if node_type.endswith("Event"):
        return EVENT_SIZE
    if node_type.endswith("Gateway"):
        return GATEWAY_SIZE
    return TASK_SIZE


def _back_edges(spec: ProcessSpec, successors: dict[str, list[tuple[str, int]]]) -> set[int]:
    state: dict[str, int] = {}
    back: set[int] = set()
    roots = [node.id for node in spec.nodes if node.type == "startEvent"] + [node.id for node in spec.nodes]
    for root in roots:
        if state.get(root):
            continue
        state[root] = 1
        stack = [(root, iter(successors[root]))]
        while stack:
            current, children = stack[-1]
            child = next(children, None)
            if child is None:
                state[current] = 2
                stack.pop()
                continue
            target, index = child
            if state.get(target) == 1:
                back.add(index)
            elif not state.get(target):
                state[target] = 1
                stack.append((target, iter(successors[target])))
    return back


def compute_layout(spec: ProcessSpec) -> Layout:
    ids = [node.id for node in spec.nodes]
    nodes = {node.id: node for node in spec.nodes}
    successors: dict[str, list[tuple[str, int]]] = {node_id: [] for node_id in ids}
    predecessors: dict[str, list[tuple[str, int]]] = {node_id: [] for node_id in ids}
    for index, flow in enumerate(spec.flows):
        if flow.source in nodes and flow.target in nodes:
            successors[flow.source].append((flow.target, index))
            predecessors[flow.target].append((flow.source, index))

    back = _back_edges(spec, successors)
    forward_succ = {key: [target for target, index in value if index not in back] for key, value in successors.items()}
    forward_pred = {key: [source for source, index in value if index not in back] for key, value in predecessors.items()}

    layer = {node_id: 0 for node_id in ids}
    indegree = {node_id: len(forward_pred[node_id]) for node_id in ids}
    queue = deque(node_id for node_id in ids if indegree[node_id] == 0)
    while queue:
        current = queue.popleft()
        for target in forward_succ[current]:
            layer[target] = max(layer[target], layer[current] + 1)
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)

    lane_ids: list[str | None] = [lane.id for lane in spec.lanes] or [None]
    lane_of = {node_id: (nodes[node_id].lane if spec.lanes else None) for node_id in ids}
    row: dict[str, int] = {}
    occupied: set[tuple[str | None, int, int]] = set()
    position = {node_id: index for index, node_id in enumerate(ids)}

    def sort_key(node_id: str) -> tuple[int, int, int]:
        placed = [source for source in forward_pred[node_id] if source in row]
        if not placed:
            return (0, 0, position[node_id])
        source = min(placed, key=lambda item: row[item])
        return (row[source], forward_succ[source].index(node_id), position[node_id])

    for current_layer in range(max(layer.values(), default=0) + 1):
        for node_id in sorted((n for n in ids if layer[n] == current_layer), key=sort_key):
            lane = lane_of[node_id]
            same_lane = [source for source in forward_pred[node_id] if source in row and lane_of[source] == lane]
            desired = 0
            if len(same_lane) == 1:
                source = same_lane[0]
                siblings = [target for target in forward_succ[source] if lane_of[target] == lane]
                desired = row[source] + (siblings.index(node_id) if len(siblings) > 1 else 0)
            elif same_lane:
                desired = min(row[source] for source in same_lane)
            while (lane, current_layer, desired) in occupied:
                desired += 1
            occupied.add((lane, current_layer, desired))
            row[node_id] = desired

    loop_lanes = {lane_of[spec.flows[index].source] for index in back}
    content_x = ORIGIN + POOL_LABEL + LANE_LABEL + CONTENT_MARGIN if spec.lanes else ORIGIN + CONTENT_MARGIN
    max_layer = max(layer.values(), default=0)
    content_right = content_x + max_layer * COLUMN_WIDTH + TASK_SIZE[0] + CONTENT_MARGIN

    layout = Layout()
    lane_top: dict[str | None, float] = {}
    lane_height: dict[str | None, float] = {}
    y = ORIGIN
    for lane in lane_ids:
        rows = max((row[n] for n in ids if lane_of[n] == lane), default=0) + 1
        padding = LOOP_PADDING if lane in loop_lanes else 0
        lane_top[lane] = y + padding
        lane_height[lane] = rows * ROW_HEIGHT + padding
        if lane is not None:
            layout.lanes[lane] = Bounds(ORIGIN + POOL_LABEL, y, content_right - ORIGIN - POOL_LABEL, lane_height[lane])
        y += lane_height[lane]
    if spec.lanes:
        layout.pool = Bounds(ORIGIN, ORIGIN, content_right - ORIGIN, y - ORIGIN)

    for node_id in ids:
        width, height = _size(nodes[node_id].type)
        center_x = content_x + TASK_SIZE[0] / 2 + layer[node_id] * COLUMN_WIDTH
        center_y = lane_top[lane_of[node_id]] + row[node_id] * ROW_HEIGHT + ROW_HEIGHT / 2
        layout.shapes[node_id] = Bounds(center_x - width / 2, center_y - height / 2, width, height)
        if nodes[node_id].is_gateway and nodes[node_id].name:
            # Above the gateway: branch flows leave through the bottom.
            layout.shape_labels[node_id] = Bounds(center_x - 50, center_y - height / 2 - 34, 100, 27)

    loops_per_lane: dict[str | None, int] = {}
    for index, flow in enumerate(spec.flows):
        source, target = layout.shapes[flow.source], layout.shapes[flow.target]
        if index in back:
            lane = lane_of[flow.source]
            offset = loops_per_lane.get(lane, 0)
            loops_per_lane[lane] = offset + 1
            route_y = lane_top[lane] - LOOP_PADDING / 2 - (offset % 3) * 6
            points = [(source.cx, source.y), (source.cx, route_y), (target.cx, route_y), (target.cx, target.y)]
        elif abs(source.cy - target.cy) < 1:
            points = [(source.right, source.cy), (target.x, target.cy)]
        elif nodes[flow.source].is_gateway and len(forward_succ[flow.source]) > 1:
            exit_y = source.bottom if target.cy > source.cy else source.y
            points = [(source.cx, exit_y), (source.cx, target.cy), (target.x, target.cy)]
        elif nodes[flow.target].is_gateway and len(forward_pred[flow.target]) > 1:
            entry_y = target.bottom if source.cy > target.cy else target.y
            points = [(source.right, source.cy), (target.cx, source.cy), (target.cx, entry_y)]
        else:
            bend_x = target.cx - COLUMN_WIDTH / 2
            if bend_x <= source.right:
                bend_x = (source.right + target.x) / 2
            points = [(source.right, source.cy), (bend_x, source.cy), (bend_x, target.cy), (target.x, target.cy)]
        layout.edges.append(points)
        layout.labels.append(_label_bounds(flow.name, points) if flow.name else None)
    return layout


def _label_bounds(text: str, points: list[Point]) -> Bounds:
    width = min(90, 8 + 6 * len(text))
    if len(points) >= 3:
        x, y = points[1]
    else:
        x, y = points[0]
    return Bounds(x + 6, y - 20, width, 14)

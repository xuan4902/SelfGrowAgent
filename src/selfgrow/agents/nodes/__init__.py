"""五个角色节点：占卜师(诊断) / 制图师(规划) / 讲师(学习) / 陪练武士(演练) / 史官(复盘+毕业)。"""

from selfgrow.agents.nodes.diagnose import diagnose_node
from selfgrow.agents.nodes.graduate import graduate_node
from selfgrow.agents.nodes.learn import learn_node
from selfgrow.agents.nodes.plan import plan_node
from selfgrow.agents.nodes.review import review_node
from selfgrow.agents.nodes.spar import spar_node

__all__ = [
    "diagnose_node",
    "plan_node",
    "learn_node",
    "spar_node",
    "review_node",
    "graduate_node",
]

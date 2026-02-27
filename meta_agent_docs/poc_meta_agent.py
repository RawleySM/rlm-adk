import math
import random
from typing import Dict, List, Tuple

class VADCFRNode:
    """Represents an Information Set ($I$) in the Meta-Game."""
    def __init__(self, info_set_name: str):
        self.info_set = info_set_name
        self.actions: List[str] = []
        
        # State tracking per action
        self.R: Dict[str, float] = {}              # Cumulative Regret ($R$)
        self.strategy_sum: Dict[str, float] = {}   # For stabilized meta-policy
        
        self.ewma = 0.0                            # Volatility EWMA (Global to Information Set)
        self.ewma_weight = 0.1
        self.iteration = 0
        
    def add_action(self, action_name: str):
        if action_name not in self.actions:
            self.actions.append(action_name)
            self.R[action_name] = 0.0
            self.strategy_sum[action_name] = 0.0

    def get_evaluation_strategy(self) -> Dict[str, float]:
        """Evaluation Solver: Returns last-iterate strategy using Regret Matching."""
        strategy = {}
        norm_sum = 0.0
        for a in self.actions:
            strategy[a] = max(0.0, self.R[a])
            norm_sum += strategy[a]
            
        if norm_sum > 0:
            for a in self.actions:
                strategy[a] /= norm_sum
        else:
            # Uniform random if all regrets are <= 0 (this triggers SHOR-PSRO in the router)
            n = len(self.actions)
            for a in self.actions:
                strategy[a] = 1.0 / n if n > 0 else 0.0
        return strategy

    def update(self, action_utilities: Dict[str, float]):
        """Applies VAD-CFR mathematical mechanisms from the specification."""
        self.iteration += 1
        t = self.iteration
        
        current_strategy = self.get_evaluation_strategy()
        expected_u = sum(current_strategy[a] * action_utilities.get(a, 0.0) for a in self.actions)
        
        # Calculate instantaneous regrets
        inst_regrets = {a: action_utilities.get(a, 0.0) - expected_u for a in self.actions}
        
        # 1. & 2. Volatility Update (EWMA) - Global to Info Set
        inst_mag = max((abs(r) for r in inst_regrets.values()), default=0.0)
        self.ewma = self.ewma_weight * inst_mag + (1.0 - self.ewma_weight) * self.ewma
        volatility = min(1.0, self.ewma / 2.0)
        
        # 3. Adaptive Discount Parameters
        alpha = max(0.1, 1.5 - 0.5 * volatility)
        beta = min(alpha, -0.1 - 0.5 * volatility)
        
        t_plus_one = float(t + 1)
        disc_pos = (t_plus_one ** alpha) / (t_plus_one ** alpha + 1.0)
        disc_neg = (t_plus_one ** beta) / (t_plus_one ** beta + 1.0)
        
        for a in self.actions:
            r = inst_regrets[a]
            
            # 4. Asymmetric Boosting
            r_boosted = r * 1.1 if r > 0 else r
            
            # 5. Apply discount based on sign of previous cumulative regret
            discount = disc_pos if self.R[a] >= 0 else disc_neg
            self.R[a] = (self.R[a] * discount) + r_boosted
            
            # 6. Negative Regret Cap
            self.R[a] = max(-20.0, self.R[a])
            
            # 7. Stabilized Meta-Policy (Regret-Magnitude Weighting & Hard Warm-Start)
            # Using t > 5 instead of 500 for faster PoC demonstration
            if t > 5: 
                weight = max(0.0, self.R[a]) 
                self.strategy_sum[a] += current_strategy[a] * weight

class MetaAgentSimulator:
    def __init__(self):
        self.nodes: Dict[str, VADCFRNode] = {}
        
    def get_node(self, info_set: str) -> VADCFRNode:
        if info_set not in self.nodes:
            self.nodes[info_set] = VADCFRNode(info_set)
        return self.nodes[info_set]

    def trigger_shor_psro(self, node: VADCFRNode):
        """Simulates SHOR-PSRO Recursive Tool Generation."""
        print(f"\\n[SHOR-PSRO] All tools failing or uninitialized. Triggering Oracle Expansion for '{node.info_set}'...")
        tool_id = len(node.actions) + 1
        new_action_name = f"evolved_tool_v{tool_id}"
        node.add_action(new_action_name)
        print(f"[SHOR-PSRO] Dispatched Explorers & Refiners. Synthesized new tool: '{new_action_name}'.\\n")
        return new_action_name

    def simulate_task(self, info_set: str, environment_simulator) -> Tuple[str, float, Dict[str, float]]:
        node = self.get_node(info_set)
        
        # Check Meta-Game State: Trigger expansion if empty or all regrets <= 0
        if not node.actions or all(node.R.get(a, 0) <= 0 for a in node.actions):
            self.trigger_shor_psro(node)
            
        strategy = node.get_evaluation_strategy()
        
        # Select action based on probability distribution
        r = random.random()
        cumulative = 0.0
        chosen_action = node.actions[-1] # Fallback
        for a, prob in strategy.items():
            cumulative += prob
            if r <= cumulative:
                chosen_action = a
                break
            
        # Execute and Evaluate
        utilities = {a: environment_simulator(a) for a in node.actions}
        utility = utilities[chosen_action]
        
        # Update Meta-Memory
        node.update(utilities)
        
        return chosen_action, utility, node.R.copy()

def run_simulation():
    sim = MetaAgentSimulator()
    info_set = "TaskType.SYNTAX_RESOLUTION"
    
    # Simulate environment where early tools are bad, forcing evolution to better tools
    def env(action):
        if action == "evolved_tool_v1": return random.uniform(-2, -0.5) # Consistently fails
        if action == "evolved_tool_v2": return random.uniform(-1.5, -0.1) # Also fails
        if action == "evolved_tool_v3": return random.uniform(1.0, 3.0) # Highly successful
        return random.uniform(-1, 1)
        
    print(f"--- RLM ADK Meta-Agent Simulator ---")
    print(f"Information Set: {info_set}")
    
    for epoch in range(1, 41):
        action, utility, regrets = sim.simulate_task(info_set, env)
        if epoch % 5 == 0 or epoch == 1 or "v3" in action and epoch < 10:
            node = sim.get_node(info_set)
            strat = node.get_evaluation_strategy()
            print(f"Iter {epoch:02d} | Selected: {action:<15} | Utility: {utility:>5.2f}")
            regrets_dict = {k: round(v, 2) for k, v in regrets.items()}
            strat_dict = {k: round(v, 2) for k, v in strat.items()}
            print(f"  Regrets : {regrets_dict}")
            print(f"  Strategy: {strat_dict}")
            print("-" * 60)

if __name__ == '__main__':
    run_simulation()
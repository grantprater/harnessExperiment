"""Genetic Evolution of Skills and MAP-Elites Archive for Minecraft.

Implements code-as-skill evolution:
- SkillGenome: Composed of perceptual probe thresholds and action execution policies.
- MAP-Elites Archive: Preserves behavioral diversity across resource tiers and domains.
- Genetic Operators: Parameter mutation, structural perturbation, and compositional crossover.
- Fitness Grounding: Evaluated directly against formal physical ledger deltas.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
import random
from typing import Any, Callable, Dict, List, Optional, Tuple

from reticle.adapters.minecraft_adapter import SimulatedMinecraftEnvironment


@dataclass
class SkillGenome:
    skill_id: str
    name: str
    niche: Tuple[str, str]  # (ResourceTier, Domain) e.g., ("wood", "gathering"), ("stone", "mining")
    parameters: Dict[str, float]  # e.g., {"reach_distance": 3.5, "timeout_ticks": 100, "retry_limit": 2}
    policy_fn: Optional[Callable[[SimulatedMinecraftEnvironment, Dict[str, float]], Dict[str, Any]]] = None
    fitness: float = -1.0
    generation: int = 0
    parent_ids: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class MAPElitesSkillArchive:
    """Quality-Diversity (QD) grid maintaining optimal skill champions per behavioral niche."""

    def __init__(self, tiers: List[str], domains: List[str]):
        self.tiers = tiers
        self.domains = domains
        # Grid: (tier, domain) -> SkillGenome
        self.cells: Dict[Tuple[str, str], SkillGenome] = {}

    def insert(self, genome: SkillGenome) -> bool:
        """Insert genome if cell is empty or genome has higher fitness than existing occupant."""
        niche = genome.niche
        if niche[0] not in self.tiers or niche[1] not in self.domains:
            # Out of bounds niche
            return False

        current = self.cells.get(niche)
        if current is None or genome.fitness > current.fitness:
            self.cells[niche] = copy.deepcopy(genome)
            return True
        return False

    def get_champion(self, tier: str, domain: str) -> Optional[SkillGenome]:
        return self.cells.get((tier, domain))

    def get_all_champions(self) -> List[SkillGenome]:
        return list(self.cells.values())

    def coverage_ratio(self) -> float:
        total_cells = len(self.tiers) * len(self.domains)
        return len(self.cells) / total_cells if total_cells > 0 else 0.0


class SkillEvolutionEngine:
    """Orchestrates mutation, crossover, and fitness evaluation across skill generations."""

    def __init__(
        self,
        archive: MAPElitesSkillArchive,
        mutation_rate: float = 0.3,
        crossover_rate: float = 0.4
    ):
        self.archive = archive
        self.mutation_rate = mutation_rate
        self.crossover_rate = crossover_rate
        self.generation_count: int = 0

    def evaluate_fitness(
        self,
        genome: SkillGenome,
        env_factory: Callable[[], SimulatedMinecraftEnvironment],
        target_item: str,
        max_duration_ticks: int = 200
    ) -> float:
        """Evaluates skill genome against a deterministic sandbox trial."""
        if not genome.policy_fn:
            return 0.0

        env = env_factory()
        pre_yield = env.inventory.get(target_item, 0)
        pre_health = env.health
        pre_ticks = env.total_ticks

        try:
            res = genome.policy_fn(env, genome.parameters)
            success = res.get("success", False)
        except Exception:
            return 0.0

        post_yield = env.inventory.get(target_item, 0)
        delta_yield = post_yield - pre_yield
        delta_ticks = env.total_ticks - pre_ticks
        damage_taken = max(0.0, pre_health - env.health)

        # Multi-objective fitness function:
        # High yield + Fast execution - Damage penalty - Failure penalty
        time_efficiency = 100.0 / (delta_ticks + 1)
        yield_score = delta_yield * 50.0
        success_bonus = 20.0 if success else -10.0
        damage_penalty = damage_taken * 15.0

        fitness = max(0.0, yield_score + time_efficiency + success_bonus - damage_penalty)
        genome.fitness = round(fitness, 2)
        return genome.fitness

    def mutate(self, genome: SkillGenome, new_id: str) -> SkillGenome:
        """Applies parameter Gaussian perturbation and policy threshold adjustments."""
        child_params = copy.deepcopy(genome.parameters)
        for key, val in child_params.items():
            if random.random() < self.mutation_rate:
                # Add Gaussian jitter (approx +- 15%)
                perturbation = random.gauss(0, 0.15 * max(1.0, abs(val)))
                child_params[key] = max(0.1, round(val + perturbation, 2))

        return SkillGenome(
            skill_id=new_id,
            name=f"{genome.name}_mut_{random.randint(100, 999)}",
            niche=genome.niche,
            parameters=child_params,
            policy_fn=genome.policy_fn,
            generation=genome.generation + 1,
            parent_ids=[genome.skill_id],
            metadata={"mutation_type": "param_jitter"}
        )

    def crossover(self, parent_a: SkillGenome, parent_b: SkillGenome, new_id: str) -> SkillGenome:
        """Recombines parameter genes between two parent skills."""
        child_params = {}
        all_keys = set(parent_a.parameters.keys()).union(set(parent_b.parameters.keys()))
        for k in all_keys:
            val_a = parent_a.parameters.get(k, 1.0)
            val_b = parent_b.parameters.get(k, 1.0)
            # Blend crossover
            child_params[k] = round(0.5 * (val_a + val_b), 2)

        # Inherit policy from fitter parent
        chosen_policy = parent_a.policy_fn if parent_a.fitness >= parent_b.fitness else parent_b.policy_fn
        chosen_niche = parent_a.niche if parent_a.fitness >= parent_b.fitness else parent_b.niche

        return SkillGenome(
            skill_id=new_id,
            name=f"xover_{parent_a.name[:5]}_{parent_b.name[:5]}",
            niche=chosen_niche,
            parameters=child_params,
            policy_fn=chosen_policy,
            generation=max(parent_a.generation, parent_b.generation) + 1,
            parent_ids=[parent_a.skill_id, parent_b.skill_id],
            metadata={"crossover": True}
        )

    def run_evolution_step(
        self,
        population: List[SkillGenome],
        env_factory: Callable[[], SimulatedMinecraftEnvironment],
        target_item: str,
        target_pop_size: int = 10
    ) -> List[SkillGenome]:
        """Evaluates population, inserts champions into MAP-Elites, and generates next generation."""
        # 1. Evaluate all individuals
        for ind in population:
            self.evaluate_fitness(ind, env_factory, target_item=target_item)
            self.archive.insert(ind)

        # 2. Sort by fitness
        population.sort(key=lambda x: x.fitness, reverse=True)
        next_gen: List[SkillGenome] = []

        # Elitism: keep top 2
        next_gen.extend(population[:2])

        # 3. Breed remaining slots using Mutation & Crossover
        while len(next_gen) < target_pop_size:
            if len(population) >= 2 and random.random() < self.crossover_rate:
                p1, p2 = random.sample(population[:max(2, len(population) // 2)], 2)
                child = self.crossover(p1, p2, new_id=f"gen_{self.generation_count+1}_{len(next_gen)}")
            else:
                parent = random.choice(population[:max(1, len(population) // 2)])
                child = self.mutate(parent, new_id=f"gen_{self.generation_count+1}_{len(next_gen)}")
            next_gen.append(child)

        self.generation_count += 1
        return next_gen

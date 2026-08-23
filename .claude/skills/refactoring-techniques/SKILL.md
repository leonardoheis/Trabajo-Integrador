---
name: refactoring-techniques
description: Use when you've named a code smell (or design problem) and need the concrete refactoring technique that fixes it — extracting a method, moving a field, replacing a conditional with polymorphism, introducing a parameter object, and similar. Triggers on "how do I refactor this", "what's this refactoring called", "extract this into", "how do I clean this up", or right after a code-smells finding when it's time to apply the fix rather than just name the problem.
---

# Refactoring Techniques

Reference: https://refactoring.guru/refactoring/catalog

## Overview

This is the cure catalog, paired with the [[code-smells]] skill's diagnosis catalog. `code-smells` names *what's wrong* (Long Method, Feature Envy, Primitive Obsession); this skill names *the specific mechanical technique that fixes it* (Extract Method, Move Method, Replace Data Value with Object) — each technique here is a named, repeatable transformation, not a one-off fix improvised for this file.

## MANDATORY RULE: Name the Technique Before Applying It

**State which named technique you're using before editing.** "I'll apply Extract Method to pull lines 40-58 into `_validate_headers()`" is a plan; silently restructuring code without naming the move hides the reasoning from review and makes the diff harder to trust. If no technique in this catalog fits, say so explicitly rather than forcing the nearest-sounding name onto an ad-hoc change.

## Quick Reference — Six Categories

| Category | What it addresses | Techniques |
|---|---|---|
| **Composing Methods** | A method's internals are hard to read or duplicated | Extract Method, Inline Method, Extract Variable, Inline Temp, Replace Temp with Query, Split Temporary Variable, Remove Assignments to Parameters, Replace Method with Method Object, Substitute Algorithm |
| **Moving Features between Objects** | Behavior/data lives on the wrong class | Move Method, Move Field, Extract Class, Inline Class, Hide Delegate, Remove Middle Man, Introduce Foreign Method, Introduce Local Extension |
| **Organizing Data** | Fields, primitives, or type codes need a better shape | Self Encapsulate Field, Replace Data Value with Object, Change Value to Reference, Change Reference to Value, Replace Array with Object, Duplicate Observed Data, Change Unidirectional Association to Bidirectional, Change Bidirectional Association to Unidirectional, Replace Magic Number with Symbolic Constant, Encapsulate Field, Encapsulate Collection, Replace Type Code with Class, Replace Type Code with Subclasses, Replace Type Code with State/Strategy, Replace Subclass with Fields |
| **Simplifying Conditional Expressions** | Branching logic is tangled or duplicated | Decompose Conditional, Consolidate Conditional Expression, Consolidate Duplicate Conditional Fragments, Remove Control Flag, Replace Nested Conditional with Guard Clauses, Replace Conditional with Polymorphism, Introduce Null Object, Introduce Assertion |
| **Simplifying Method Calls** | A method's signature or call sites are awkward | Rename Method, Add Parameter, Remove Parameter, Separate Query from Modifier, Parameterize Method, Replace Parameter with Explicit Methods, Preserve Whole Object, Replace Parameter with Method Call, Introduce Parameter Object, Remove Setting Method, Hide Method, Replace Constructor with Factory Method, Replace Error Code with Exception, Replace Exception with Test |
| **Dealing with Generalization** | A class hierarchy is missing or badly shaped | Pull Up Field, Pull Up Method, Pull Up Constructor Body, Push Down Method, Push Down Field, Extract Subclass, Extract Superclass, Extract Interface, Collapse Hierarchy, Form Template Method, Replace Inheritance with Delegation, Replace Delegation with Inheritance |

## Composing Methods

| Technique | Use when | Fix direction |
|---|---|---|
| **Extract Method** | A code fragment can be grouped together and given a name that explains its purpose | Move the fragment into a new, well-named method; replace the original code with a call to it |
| **Inline Method** | A method's body is as clear as its name — the indirection adds nothing | Replace calls to the method with its body, then remove the method |
| **Extract Variable** | An expression is hard to read | Put the result (or part of it) in a temporary variable named for what it means |
| **Inline Temp** | A temp variable is assigned once from a simple expression and adds no clarity | Replace all references to the temp with the expression itself |
| **Replace Temp with Query** | A temp holds the result of an expression that other methods might also need | Extract the expression into a method; replace the temp's references with calls to it |
| **Split Temporary Variable** | A local variable is assigned to more than once for more than one purpose (a loop accumulator excepted) | Use a separate variable for each responsibility |
| **Remove Assignments to Parameters** | Code assigns a new value to a parameter, obscuring pass-by-value semantics | Use a local variable instead of reassigning the parameter |
| **Replace Method with Method Object** | A long method's local variables are so intertwined you can't apply Extract Method cleanly | Turn the method into its own class, with the locals as fields — now the method can be freely decomposed |
| **Substitute Algorithm** | An algorithm needs replacing with one that is clearer or does the job better | Replace the method body wholesale with the new algorithm |

## Moving Features between Objects

| Technique | Use when | Fix direction |
|---|---|---|
| **Move Method** | A method is used more by another class than by its own | Create a new method on the class it uses most, move the body there, turn the old method into a delegator or remove it |
| **Move Field** | A field is used more by another class than its own | Create the field on the target class, redirect all references |
| **Extract Class** | One class is doing the work of two | Create a new class, move the relevant fields/methods into it |
| **Inline Class** | A class isn't doing enough to earn its keep, and won't grow into more | Move all its features into another class and delete it |
| **Hide Delegate** | A client calls a delegate class through an accessor, coupling it to the delegate's interface | Create methods on the server that hide the delegate entirely |
| **Remove Middle Man** | A class does nothing but delegate to another — too much of this makes classes hard to follow | Let the client call the delegate directly |
| **Introduce Foreign Method** | A utility class you can't modify is missing a method you need | Add the method to a client class, taking an instance of the utility class as its first argument |
| **Introduce Local Extension** | A utility class you can't modify needs several missing methods | Create a subclass or wrapper with the extra methods |

## Organizing Data

| Technique | Use when | Fix direction |
|---|---|---|
| **Self Encapsulate Field** | You need flexible access to a field (e.g. lazy init, subclass override) | Create getter/setter, use only those internally too |
| **Replace Data Value with Object** | A data item needs behavior or associated data beyond a bare value | Turn it into an object |
| **Change Value to Reference** | Many equal instances of a class should be represented by one shared object | Turn it into a reference object (e.g. via a factory/registry) |
| **Change Reference to Value** | A reference object is small, immutable, and awkward to manage the lifecycle of | Turn it into a value object |
| **Duplicate Observed Data** | Domain data lives in a GUI class and needs to be used by non-GUI code | Split the data into a domain object, keep the GUI in sync via observer |
| **Change Unidirectional Association to Bidirectional** | Two classes each need to use the other's features but only one direction of link exists | Add the back-pointer and code to keep both ends consistent |
| **Change Bidirectional Association to Unidirectional** | One end of a two-way association no longer needs the other | Drop the unused direction |
| **Replace Array with Object** | An array holds several different kinds of data | Replace it with an object with a named field per element |
| **Replace Magic Number with Symbolic Constant** | A literal number carries meaning that isn't obvious from context | Name it as a constant |
| **Encapsulate Field** | A public field is accessed directly across the class boundary | Make it private, add accessors |
| **Encapsulate Collection** | A method returns a collection field directly, letting callers mutate internal state | Return a read-only view or copy; add explicit add/remove methods |
| **Replace Type Code with Class** | A field holds a type code whose value doesn't affect program behavior | Replace the raw code with a small class |
| **Replace Type Code with Subclasses** | A type code affects behavior via conditionals scattered across the class | Create a subclass per code value, use polymorphism instead of conditionals |
| **Replace Type Code with State/Strategy** | Type-code-driven behavior needs subclassing, but the class already has a subclass hierarchy for another reason | Use a State/Strategy object instead of subclassing the type code directly |
| **Replace Subclass with Fields** | Subclasses differ only in methods that return constant data | Replace the subclasses with fields on the parent, then remove them |

## Simplifying Conditional Expressions

| Technique | Use when | Fix direction |
|---|---|---|
| **Decompose Conditional** | A complex `if/then/else` obscures what's actually being checked and done | Extract the condition and each branch into well-named methods |
| **Consolidate Conditional Expression** | A sequence of conditionals all lead to the same action | Combine them into a single expression (via and/or) |
| **Consolidate Duplicate Conditional Fragments** | The same code appears inside every branch of a conditional | Move the duplicated code outside the conditional entirely |
| **Remove Control Flag** | A boolean variable is used to control when a loop/sequence should stop | Use `break`, `continue`, or `return` directly instead |
| **Replace Nested Conditional with Guard Clauses** | Nested conditionals bury the normal-path logic under special-case checks | Pull each special case out as an early-return guard clause, flattening the rest |
| **Replace Conditional with Polymorphism** | A conditional branches on an object's type or a type-like property | Move each branch to an overriding method in the relevant subclass |
| **Introduce Null Object** | Repeated `if x is not None` checks exist purely to avoid calling methods on a missing object | Replace `None` with an object that implements the same interface with default/no-op behavior — see also the `stop-using-none` skill |
| **Introduce Assertion** | Code has an unstated assumption about a value or state that must hold for correctness | Make the assumption explicit with an assertion |

## Simplifying Method Calls

| Technique | Use when | Fix direction |
|---|---|---|
| **Rename Method** | A method's name doesn't say what it does | Rename it, update all call sites |
| **Add Parameter** | A method needs more information from its caller to do its job | Add a parameter carrying that information |
| **Remove Parameter** | A parameter is no longer used in the method body | Delete it, update all call sites |
| **Separate Query from Modifier** | One method both returns a value and has a side effect | Split into a query method (no side effect) and a modifier method (no return value) |
| **Parameterize Method** | Several methods do near-identical things but with different literal values | Merge into one method with a parameter for the varying value |
| **Replace Parameter with Explicit Methods** | A method runs different code paths based on a parameter's value | Create a separate method per value the parameter can take |
| **Preserve Whole Object** | Several values are extracted from one object just to pass them individually | Pass the whole object instead |
| **Replace Parameter with Method Call** | A caller does a lookup just to pass its result as a parameter the callee could compute itself | Have the callee call the lookup method directly, drop the parameter |
| **Introduce Parameter Object** | A group of parameters keeps traveling together across method signatures | Combine them into a single parameter object |
| **Remove Setting Method** | A field should be set only at construction and never change afterward | Remove its setter |
| **Hide Method** | A method is never used outside its own class/hierarchy | Make it private or protected |
| **Replace Constructor with Factory Method** | Object construction needs logic beyond simple field assignment (e.g. choosing a subclass) | Replace the constructor call with a factory method |
| **Replace Error Code with Exception** | A method returns a special value to signal an error, forcing callers to check every time | Raise a specific exception instead — see this project's `.claude/learnings.md` exception style |
| **Replace Exception with Test** | An exception is used to handle a condition the caller could have checked for up front | Add the check before the call, remove the exception handling |

## Dealing with Generalization

| Technique | Use when | Fix direction |
|---|---|---|
| **Pull Up Field** | Subclasses each independently declare the same field | Move the field to the superclass |
| **Pull Up Method** | Subclasses each independently implement an identical method | Move the method to the superclass |
| **Pull Up Constructor Body** | Subclass constructors share substantial common setup code | Extract the common part into a superclass constructor, call it via `super()` |
| **Push Down Method** | A superclass method is only relevant to some of its subclasses | Move it down to just those subclasses |
| **Push Down Field** | A superclass field is only used by some of its subclasses | Move it down to just those subclasses |
| **Extract Subclass** | A class has features that are only used in some cases | Create a subclass for that case, move the relevant features into it |
| **Extract Superclass** | Two classes share common fields/methods | Create a shared superclass, move the common parts into it |
| **Extract Interface** | Several clients use the same subset of a class's interface, or two classes share part of an interface | Extract that subset into its own interface (Protocol/ABC) |
| **Collapse Hierarchy** | A subclass and its superclass have drifted so close together they're barely distinct | Merge them into one class |
| **Form Template Method** | Two subclasses implement similar algorithms with the same steps in the same order but different details | Move the overall structure to the superclass as a template method, leave the varying steps abstract |
| **Replace Inheritance with Delegation** | A subclass uses only part of its superclass's interface, or doesn't want to inherit all its data | Create a field holding the "superclass" instance instead, delegate to it, drop the inheritance |
| **Replace Delegation with Inheritance** | A class delegates to another via many near-pass-through methods, and the delegate relationship is really "is-a" | Make the delegating class inherit from the delegate instead, remove the pass-through methods |

## Common Mistakes

| Mistake | Fix |
|---|---|
| Applying a technique because its name sounds close, without checking the "use when" condition actually holds | Re-read the condition; a mismatch here produces a change that looks structured but doesn't fix the real problem |
| Treating this catalog as a checklist to run top-to-bottom | Each technique is a response to a specific smell ([[code-smells]]) or a specific request — apply only the one that matches what's actually wrong |
| Renaming a technique instead of naming the real one | If nothing here fits, say the change is ad-hoc rather than forcing a catalog name onto it |
| Using Extract Class / Extract Method reflexively for any "this file is long" complaint | Confirm there's an actual second responsibility or duplicated fragment first — see code-smells' Speculative Generality and YAGNI guidance |
| Chasing Replace Conditional with Polymorphism for a conditional that only ever has two stable branches | Polymorphism pays off when branches multiply or recur across methods; a single stable two-way branch is often clearer as-is |

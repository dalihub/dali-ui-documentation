---
id: animation
title: "animation"
sidebar_label: "animation"
---
## Overview

The [animation](./animation.md) module provides a powerful framework for creating fluid, time-based visual transitions and property modifications within `View` components to enhance application interactivity. Developers can orchestrate complex UI changes by manipulating properties over time, applying physics-based easing, or defining geometric paths for movement.

## Declarative View Animations

The framework simplifies common UI transitions by providing high-level bridges and specifications that allow for concise, readable, and chainable [animation](./animation.md) definitions. Using `ViewAnimationBridge` or `ViewAnimationSpec`, developers can define property changes such as opacity, scale, and position without manually managing the lifecycle of the underlying `Animation` [object](./object.md) for every single property transition.

```cpp
Animation animation = Animation::New(2.0f);
ViewAnimationBridge bridge(animation, myView);
bridge.PositionX(100.0f, Duration(1.0f))
      .PositionY(200.0f, Duration(1.0f), AlphaFunction::LINEAR, Duration(1.0f))
      .Opacity(0.5f, Duration(0.5f));
animation.Play();
```

The `ViewAnimationSpec` class is particularly useful for creating reusable animation definitions that can be applied to any `View` later in the application lifecycle. Once an animation specification is constructed, the `ApplyTo` method is used to execute the defined animation sequence on a specific target.

```cpp
ViewAnimationSpec spec = ViewAnimationSpec::New();
spec.ScaleX(2.0f, Duration(1.0f))
    .ScaleY(2.0f, Duration(1.0f));

Animation animation = Animation::New(1.0f);
spec.ApplyTo(animation, myView);
animation.Play();
```

## Keyframe and Path-Based Motion

For non-linear motion or complex property curves, the module supports keyframe animation. By using `KeyFrames`, developers can define a sequence of values associated with specific time progress points, allowing the system to interpolate smoothly between these states using `AnimateBetween`.

```cpp
KeyFrames keyFrames = KeyFrames::New();
keyFrames.Add(0.0f, Property::Value(UiColor(1.0f, 0.0f, 0.0f, 1.0f)));
keyFrames.Add(1.0f, Property::Value(UiColor(0.0f, 0.0f, 1.0f, 1.0f)));

Animation animation = Animation::New(2.0f);
animation.AnimateBetween(Property(myView, Actor::Property::COLOR), keyFrames);
animation.Play();
```

Sophisticated movement along 3D geometric trajectories is achieved through the `Path` class. By adding interpolation points or generating control points via `GenerateControlPoints`, developers can animate a `View` to follow a curve. The `Animate` method on an `Animation` object facilitates this by binding a view to a path, optionally specifying a forward direction for orientation tracking.

```cpp
Path path = Path::New();
path.AddPoint(Vector3(0.0f, 0.0f, 0.0f));
path.AddPoint(Vector3(100.0f, 100.0f, 0.0f));
path.GenerateControlPoints(0.5f);

Animation animation = Animation::New(2.0f);
animation.Animate(myView, path, Vector3(0.0f, 0.0f, 1.0f));
animation.Play();
```

## Timing and Easing Control

Animation feel is governed by the `AlphaFunction` class, which defines the rate of change over time. Developers can use built-in presets or define custom easing through Bezier control points using the `AlphaFunction(const Vector2&, const Vector2&)` constructor.

For natural, lifelike motion, the module provides spring-based physics animation. By configuring `SpringData` with specific values for stiffness, damping, and mass, developers can create physical-based interactions. The `AlphaFunction(const SpringData&)` constructor or the `SpringType` enum allows for quick implementation of standard spring behaviors.

```cpp
SpringData springData(100.0f, 10.0f, 1.0f);
AlphaFunction alphaFunction(springData);

Animation animation = Animation::New(1.0f);
animation.AnimateTo(Property(myView, Actor::Property::POSITION_X), 500.0f, alphaFunction);
animation.Play();
```

## Constraint-Based Dynamic Behavior

The constraint system allows for reactive UI logic where properties of a `View` are automatically computed based on other properties or parent states. A `Constraint` is defined by a target object, a destination property, and a function or functor that calculates the new value.

> Note: The `Constraint::BAKE` action will "bake" a value when fully-applied, meaning the constrained value becomes permanent even if the constraint is later removed.

```cpp
Constraint constraint = Constraint::New<float>(myView, Actor::Property::OPACITY, EqualToConstraint());
constraint.AddSource(LocalSource(Actor::Property::OPACITY));
constraint.Apply();
```

Constraints can be applied to different execution stages using `Apply` (before transform) or `ApplyPost` (after transform), providing flexibility in the render pipeline. Sources such as `LocalSource`, `ParentSource`, or arbitrary `Source` objects allow the constraint to react to changes in relevant dependencies.

## Advanced Property Constraining

The `LinearConstrainer` class provides an efficient, pre-defined way to apply linear relationships between property sources and targets. This is ideal for scenarios like synchronizing progress values or scaling properties linearly across multiple elements.

The system uses `Apply` to define the target property, the source property, and the range for mapping values. This ensures consistent and performant visual updates across complex UI hierarchies without the overhead of custom function constraints.

```cpp
LinearConstrainer constrainer = LinearConstrainer::New();
constrainer.Apply(Property(targetView, Actor::Property::POSITION_X),
                  Property(sourceView, Actor::Property::POSITION_X),
                  Vector2(0.0f, 100.0f));
```

## Lifecycle and Playback Management

The `Animation` class acts as the primary controller for all time-based property changes. Once configured with animations via methods like `AnimateTo` or `AnimateBy`, playback is managed through `Play`, `Pause`, and `Stop`.

The module allows for fine-grained control over loops using `SetLooping` and `SetLoopCount`. Developers can also monitor the animation's progress or state using `GetCurrentProgress` and `GetState`, and receive notification upon completion by connecting to the `FinishedSignal` accessor.

```cpp
Animation animation = Animation::New(2.0f);
animation.AnimateTo(Property(myView, Actor::Property::POSITION_X), 300.0f);
animation.FinishedSignal().Connect([](Animation& source) { /* Handle finish */ });

animation.Play();
animation.Pause();
animation.Stop();
```

---

> 🔗 **API Reference**: [View Original Documentation](https://dummy-doxygen.tizen.org/dali/animation)

## Overview

Dali::Ui::View is the fundamental building block for constructing modern, performant user interfaces that utilize a declarative, fluent API design.`View` It serves as the primary UI component, enabling developers to define hierarchical structures, manage spatial layouts, and handle user interactions through a consistent, type-safe interface.`View` By leveraging this class, you gain access to centralized property management, robust signal-based event handling, and efficient resource monitoring.`View`

## The Fluent Builder Pattern

Learn how to construct clean, readable UI hierarchies using method chaining and declarative syntax to initialize view properties efficiently.`View` Every property setter method within the class returns a reference to the instance, allowing developers to chain initialization calls into a single, cohesive statement.`View` This pattern significantly reduces boilerplate code and ensures that component state is fully defined at the point of creation.`View`

```cpp
View view = View::New()
  .SetName("MyView")
  .SetPositionX(100.0f)
  .SetPositionY(50.0f)
  .SetBackgroundColor(UiColor(1.0f, 0.0f, 0.0f, 1.0f));
```

## Declarative UI Composition

Master the use of Children, With, and As wrappers to build complex, nested view trees without verbose imperative code.`Children(std::initializer_list<View>)` The `Children(std::initializer_list<View>)` allows for the definition of child hierarchies directly within the initialization chain, keeping the structural intent of the UI clear.`Children(std::initializer_list<View>)` When you need to capture a reference to an intermediary view within a tree, the `As(View&)` acts as a bridge, assigning the current view to an existing handle.`As(View&)` Furthermore, the `With(F&&)` provides an injection point to execute custom logic or complex configuration on a specific component, maintaining the flow of the fluent builder chain.`With(F&&)`

```cpp
View parent = View::New();
View child1 = View::New();
View child2 = View::New();

parent.Children({
  child1.As(child1),
  child2.As(child2)
});
```

## Layout and Sizing Mechanics

Configure the spatial footprint of your components by managing margins, requested dimensions, and automated layout modes.`SetRequestedWidth(float)` You can exert fine-grained control over how a view behaves in the layout cycle by specifying `SetRequestedWidth(float)` and `SetRequestedHeight(float)` for size requirements.`SetRequestedHeight(float)` Bounds management is further supported by `SetMargin(const Extents&)` and `SetPadding(const Extents&)`, which define outer space and inner spacing respectively.`SetMargin(const Extents&)` For more complex scenarios, the layout behavior can be switched using `SetLayoutMode(LayoutMode)`, which determines how a view participates in its parent's calculation process.`SetLayoutMode(LayoutMode)`

```cpp
View view = View::New();
view.SetMargin(Extents(10.0f, 10.0f, 10.0f, 10.0f))
    .SetPadding(Extents(5.0f, 5.0f, 5.0f, 5.0f))
    .SetRequestedWidth(200.0f)
    .SetRequestedHeight(100.0f);
```

## Visual Styling and Effects

Customize the appearance of your views using corner radii, borderline configurations, and specialized render effects.`SetCornerRadius(float)` You can apply rounded corners using the `SetCornerRadius(float)`, and control the radius policy via `SetCornerRadiusPolicy(CornerRadiusPolicy)` to toggle between absolute and relative scaling.`SetCornerRadiusPolicy(CornerRadiusPolicy)` Decorative borders are managed through the `SetBorderlineWidth(float)` and `SetBorderlineColor(const UiColor&)` methods, which update the internal visual representation immediately.`SetBorderlineWidth(float)` Additionally, complex visual styles can be applied by assigning a render effect through the `SetRenderEffect(RenderEffect)`.`SetRenderEffect(RenderEffect)`

```cpp
View view = View::New()
  .SetCornerRadius(15.0f)
  .SetCornerRadiusPolicy(CornerRadiusPolicy::ABSOLUTE)
  .SetBorderlineWidth(2.0f)
  .SetBorderlineColor(UiColor(0.0f, 0.0f, 0.0f, 1.0f));
```

## Interactivity and Selection Traits

Enable user interaction and selection state for your components using the InteractiveTrait and SelectableTrait functional overlays.`AsInteractive()` By calling `AsInteractive()`, a view is equipped to handle click and long-press events, which can be further refined with a configuration lambda.`AsInteractive()` Similarly, state management is simplified by invoking `AsSelectable()`, which enables the selection model on the view.`AsSelectable()` These traits ensure that interaction logic remains modular and is only added to components that require such capabilities.`InteractiveTrait`

```cpp
View myView = View::New();
myView.AsInteractive([](InteractiveTrait interactive)
{
  interactive.SetClickable(true);
  interactive.ConnectClickedSignal(new MyCallback(), &MyCallback::OnClicked);
});

myView.AsSelectable([](SelectableTrait selectable)
{
  selectable.EnableToggleByClick(true);
  selectable.SetSelected(false);
});
```

## Event Handling and Focus Management

Define custom interaction flows by managing touch-focus policies, handling focus change signals, and navigating through view-based focus chains.`KeyEventSignal()` You can subscribe to key events via `KeyEventSignal()` or monitor changes in focus through the `FocusChangedSignal()`.`FocusChangedSignal()` To define custom navigation paths, use methods like `SetLeftFocusableView(View)` or `SetUpFocusableView(View)` to manually link views within the focus hierarchy.`SetLeftFocusableView(View)` Interaction states are also exposed via signals, such as the `ClickedSignal()` provided by the interaction trait.`ClickedSignal()`

```cpp
View view = View::New();
View target = View::New();

view.EnsureInteractiveTrait().ConnectClickedSignal(this, &MyView::OnClicked);
view.SetLeftFocusableView(target);
```

## Hierarchy and Z-Order Management

Manipulate your UI tree dynamically by inserting children, controlling depth, and adjusting the rendering order of overlapping elements.`Add(View)` While `Add(View)` is used to build the initial tree, dynamic reordering can be performed using `Raise(LayoutOrderPolicy)`, `Lower(LayoutOrderPolicy)`, `RaiseToTop(LayoutOrderPolicy)`, and `LowerToBottom(LayoutOrderPolicy)` to modify the view's z-order within its parent.`Raise(LayoutOrderPolicy)` For precise control in complex UIs, use `RaiseAbove(View, LayoutOrderPolicy)` or `LowerBelow(View, LayoutOrderPolicy)` to position a view relative to a specific sibling component.`RaiseAbove(View, LayoutOrderPolicy)`
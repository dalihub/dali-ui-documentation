---
id: layouts
title: "layouts"
sidebar_label: "layouts"
---
# Overview

The DALi layout system provides a declarative mechanism to automate UI component positioning and sizing within `View` hierarchies, ensuring responsive interfaces across varying screen dimensions. By utilizing specialized layout engines, developers can delegate coordinate calculation and alignment logic to the framework, simplifying the maintenance of complex, dynamic user interfaces.

# Getting Started with View Layouts

Layout management relies on assigning a layout engine to a container and defining rules for how children occupy available space. The primary entry point for applying these rules is the `SetLayoutParams(LayoutParams)` method, which associates a child `View` with its specific configuration.

```cpp
View parentView = View::New();
View childView = View::New();
parentView.Add(childView);

AbsoluteLayout layout = AbsoluteLayout::New();
childView.SetLayoutParams(AbsoluteLayoutParams::New());
```

The `Layout` class serves as the foundation for all layout types, while specific implementations such as `FlexLayout`, `GridLayout`, `StackLayout`, and `AbsoluteLayout` provide the algorithms required to arrange children. Each child must be provided with appropriate parameter types, such as `FlexLayoutParams` or `GridLayoutParams`, to inform the parent layout of its requirements.

# Flexbox-based Positioning

The `FlexLayout` engine enables dynamic, responsive arrangements based on the widely recognized flexbox algorithm. This approach is ideal for interfaces that must flow and wrap content as the parent container's dimensions change.

```cpp
View container = View::New();
FlexLayout layout = FlexLayout::New();
layout.SetDirection(FlexDirection::ROW);
layout.SetJustifyContent(FlexJustify::CENTER);
```

Flexbox behavior is controlled via several properties on the `FlexLayout` object. The direction of content flow is managed by `SetDirection(FlexDirection)` using `FlexDirection` values. Content justification and alignment across axes are configured via `SetJustifyContent(FlexJustify)` and `SetAlignItems(FlexAlign)`. Individual child behavior can be fine-tuned using `FlexLayoutParams`, which allows setting specific grow, shrink, and basis factors for each child.

# Grid-based Arrangements

The `GridLayout` enables tabular organization of UI elements, offering precise control over row and column structures. It is particularly useful for dashboards or forms where alignment across multiple axes is required.

```cpp
GridLayout gridLayout = GridLayout::New();
gridLayout.AddRowDefinition(GridLength::Absolute(100.0f));
gridLayout.AddColumnDefinition(GridLength::Star(1.0f));

GridLayoutParams params = GridLayoutParams::New();
params.SetRow(0);
params.SetColumn(0);
```

Grid dimensions are defined using the `GridLength` class, which supports absolute pixel values, proportional star-based sizing, and automatic sizing. After configuring the grid structure with `SetRowDefinitions(Dali::Vector<GridLength>)` and `SetColumnDefinitions(Dali::Vector<GridLength>)`, individual child views are positioned by creating `GridLayoutParams` and assigning them the desired row, column, and span indices. The alignment within a specific grid cell is controlled by `SetHorizontalAlignment(LayoutAlignment)` and `SetVerticalAlignment(LayoutAlignment)` using the `LayoutAlignment` enum.

# Stack and Absolute Positioning

Simple linear sequences and direct coordinate assignments are handled by the `StackLayout` and `AbsoluteLayout` classes. 

```cpp
StackLayout stackLayout = StackLayout::New(StackOrientation::VERTICAL);
AbsoluteLayout absoluteLayout = AbsoluteLayout::New();

View childView = View::New();
AbsoluteLayoutParams absoluteParams = AbsoluteLayoutParams::New();
absoluteParams.SetX(10.0f);
absoluteParams.SetY(20.0f);
childView.SetLayoutParams(absoluteParams);
```

The `StackLayout` automatically positions children sequentially along a single axis, which is defined as either `StackOrientation::VERTICAL` or `StackOrientation::HORIZONTAL` via the `SetOrientation(StackOrientation)` method. In contrast, the `AbsoluteLayout` provides full manual control, where children are placed using explicit bounds. Use the `AbsoluteLayoutParams` to set exact x, y, width, and height values for each child view.

# Configuring Layout Geometry

Layout geometry is governed by structures that describe dimensions, positions, and measurement constraints. The `LayoutRect` class encapsulates the four-sided geometry of a child within a layout, offering methods to get or set x, y, width, and height.

```cpp
LayoutRect rect = LayoutRect(0.0f, 0.0f, 100.0f, 200.0f);
float width = rect.GetWidth();
float height = rect.GetHeight();
```

When components are being measured by their parents, they return a `MeasuredSize` structure. This structure helps the layout controller calculate the final allocated space for a view. When working with custom layouts or specific constraints, the `ToVector2()` method is useful for converting these dimensions into a standard format.

# Managing Layout Lifecycle

Layout updates are orchestrated by the `LayoutController`, which ensures that views are re-measured and arranged in an optimized manner. The controller tracks views that have requested changes and schedules the layout process for the next cycle.

```cpp
void RequestLayoutUpdate(Window window, ViewImpl* viewImpl)
{
  LayoutController layoutController = LayoutController::Get(window);
  layoutController.RequestLayout(viewImpl);
}
```

Developers generally do not need to call the process methods directly; however, understanding the lifecycle is vital. When a property affecting the layout of a view is changed, the view signals its need for an update through the `RequestLayout(ViewImpl*)` method. The controller eventually executes the update cycle through its internal logic. On platforms or windowing environments where resizing occurs, the `OnWindowResize(int32_t, int32_t)` method ensures that the layout hierarchy synchronizes with the new window dimensions.

---

> 🔗 **API Reference**: [View Original Documentation](https://dummy-doxygen.tizen.org/dali/layouts)

## Overview

The `Label` component provides a high-performance text rendering solution in DALi, designed for displaying static or dynamic strings with advanced typography and visual styling capabilities. It serves as a specialized view for presenting text content, ensuring that layout and formatting are handled efficiently according to defined properties.

## Creating and Initializing Labels

You can instantiate a new label by calling the static factory methods provided by the class. Once created, you may configure the text content and basic display attributes to tailor the label to your specific requirements.

```cpp
Label label = Label::New("Hello World");
label.SetFontSize(24.0f);
label.SetTextColor(UiColor(1.0f, 0.0f, 0.0f, 1.0f));
```

The `New` method initializes the component, while the `SetText` method allows you to update the content dynamically. It is important to note that the handle acts as a proxy, and multiple handles can point to the same underlying text rendering instance.

## Text Styling and Typography

Labels support comprehensive typography control, allowing developers to define font family, size, weight, width, and slant. Furthermore, the framework provides support for rich text rendering through markup and advanced font variation axes.

```cpp
Label label = Label::New();
label.SetFontWeight(Text::FontWeight::BOLD);
label.SetFontSlant(Text::FontSlant::ITALIC);
```

When advanced text styling is required, you can use `SetFontVariation` to specify custom axes or use the font property methods to set weight, width, and slant directly. Enabling markup processing via `SetMarkupEnabled` allows for inline styling within the text string itself.

## Layout and Sizing

Managing text within a constrained space requires precise control over alignment, line wrapping, and scaling behaviors. The layout properties ensure that text remains readable even when content dimensions change dynamically.

```cpp
Label label = Label::New();
label.SetMultiLine(true);
label.SetHorizontalTextAlignment(Text::Alignment::CENTER);
label.SetLineWrapMode(Text::LineWrapMode::WORD);
```

The component supports both horizontal and vertical alignment settings through `SetHorizontalTextAlignment` and `SetVerticalTextAlignment`. You can control how text behaves when it exceeds the assigned bounds using `SetOverflowMode`, choosing between clipping or appending an ellipsis. Additionally, the line height can be adjusted using absolute or relative modes to influence the spacing between text lines.

## Visual Effects and Decoration

Enhance the presentation of your text by applying various visual decorations such as shadows, outlines, underlines, and strikethroughs. These effects are managed through dedicated setter methods that accept styling configuration objects.

```cpp
Label label = Label::New();
label.SetOutline(Text::Outline(UiColor(0.0f, 0.0f, 0.0f, 1.0f), 2.0f));
label.SetShadow(Text::Shadow(UiColor(0.0f, 0.0f, 0.0f, 0.5f), Vector2(2.0f, 2.0f), 0.0f));
```

Beyond standard text rendering, you can clear applied effects using methods like `ClearOutline` or `ClearShadow` when they are no longer needed. For specialized UI designs, the `SetMaskEffect` method allows you to restrict the visibility of the label to the bounds of another view.

## Dynamic Content and Animation

For text that exceeds its container, the label module provides a built-in marquee animation system. This allows content to scroll automatically, ensuring that users can view the full string without manual interaction.

```cpp
Label label = Label::New();
label.SetMarqueeTriggerPolicy(Text::MarqueeTriggerPolicy::ON_OVERFLOW);
label.SetMarqueeSpeed(50);
label.StartMarquee();
```

The marquee behavior is controlled by setting policies like `SetMarqueeTriggerPolicy` and configuring the speed, loop count, and gap via their respective setters. You can toggle the animation using `StartMarquee` and `StopMarquee`, or check its current status using `IsMarqueeRunning`.

## Event Handling and Signals

The label module exposes several signals to help you respond to layout events and user interactions. These signals facilitate asynchronous communication, which is particularly useful for rendering operations that are offloaded from the main thread.

```cpp
class MyHandler
{
public:
  void OnAnchorClicked(View view, const Dali::String &anchorId) {}
};
Label label = Label::New();
MyHandler handler;
label.AnchorClickedSignal().Connect(&handler, &MyHandler::OnAnchorClicked);
```

The `AnchorClickedSignal` is triggered when an interactive anchor is selected by the user. Other asynchronous signals, such as `AsyncRenderFinishedSignal` and `AsyncNaturalSizeComputedSignal`, provide callbacks when intensive layout or rendering calculations complete, allowing for non-blocking UI updates.

## Related Sub-Components

This feature relies on specialized modules to manage complex internal logic and behavioral overrides.

- The label-impl module provides the underlying implementation logic for text rendering and engine-level overrides. → See: [label-impl]
- The label-property-handler module is responsible for orchestrating complex property updates and synchronization within the text rendering pipeline. → See: [label-property-handler]
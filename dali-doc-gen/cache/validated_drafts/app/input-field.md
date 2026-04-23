## Overview

The InputField component provides a high-level, customizable text entry interface designed for capturing user input in mobile and wearable applications. It acts as a specialized view that manages text rendering, focus, cursor movement, and character input constraints within a single-line layout.

## Getting Started

Integrating an input interface into the scene graph begins with creating an instance of the class. Developers should ensure the component is added to the scene graph using standard parent-child management methods, such as the `Add(View)` available on parent views.

```cpp
InputField inputField = InputField::New()
  .SetText("Enter name")
  .SetFontSize(24.0f)
  .SetTextColor(UiColor::PRIMARY);
```

The component can be safely downcast from base handles using the `DownCast(BaseHandle)` if the reference type is initially generic.

## Visual Configuration & Typography

Text appearance is highly configurable, allowing for precise control over the font, size, and weight of input characters. Developers can define the font family via `SetFontFamily(Dali::String)` and adjust the font size using the `SetFontSize(float)` to meet design requirements.

Advanced stylistic elements such as shadows, outlines, underlines, and line-through styles are supported. These are applied by passing specific style structures to methods like `SetShadow(Text::Shadow)` or `SetOutline(Text::Outline)`. To remove these decorations, corresponding clear methods such as `ClearShadow()` are available. 

Color management for text and text background is handled through the `SetTextColor(UiColor)` and `SetTextBackgroundColor(UiColor)`.

```cpp
InputField inputField = InputField::New();
inputField.SetFontFamily("Arial");
inputField.SetFontSize(20.0f);
inputField.SetTextColor(UiColor(1.0f, 1.0f, 1.0f, 1.0f));
inputField.SetShadow(Text::Shadow(Vector2(2.0f, 2.0f), UiColor(0.0f, 0.0f, 0.0f, 0.5f), 1.0f));
inputField.SetUnderline(Text::Underline(true, UiColor::PRIMARY, 1.0f));
```

Font variation support is provided for sophisticated typography needs. Axis settings can be applied using the `SetFontVariation(Dali::Vector<Text::FontVariationAxis>)`, or reset using the `ClearFontVariation()`.

## Placeholder Management

Placeholder text serves as an instructional hint that appears when the input field is empty. Use the `SetPlaceholder(Dali::String)` to provide the instructional string, and the `SetPlaceholderColor(UiColor)` to define its visual presentation.

Visibility logic is controlled by the `SetShowPlaceholderOnFocus(bool)`, which determines if the placeholder remains visible once the user interacts with and focuses on the component.

```cpp
InputField inputField = InputField::New();
inputField.SetPlaceholder("Type here...");
inputField.SetPlaceholderColor(UiColor(0.5f, 0.5f, 0.5f, 1.0f));
inputField.SetShowPlaceholderOnFocus(true);
```

## Cursor & Selection Control

The cursor provides visual feedback for the current text insertion point. Its width and color can be customized using the `SetCursorWidth(int)` and `SetCursorColor(UiColor)` respectively.

For user convenience, the cursor can be set to blink automatically via the `SetCursorBlinkEnabled(bool)`. The speed of this blinking animation is dictated by the value passed to the `SetCursorBlinkInterval(float)`. The current insertion point can be programmatically adjusted at any time using the `SetCursorPosition(uint32_t)`.

When text is highlighted, the selection region's appearance is defined by the color set through the `SetSelectionColor(UiColor)`.

```cpp
InputField inputField = InputField::New();
inputField.SetCursorWidth(2);
inputField.SetCursorColor(UiColor::PRIMARY);
inputField.SetCursorBlinkEnabled(true);
inputField.SetCursorBlinkInterval(0.5f);
inputField.SetSelectionColor(UiColor(0.2f, 0.4f, 0.8f, 0.3f));
```

## Layout & Scaling

InputField provides mechanisms to ensure readability across diverse screen densities and system configurations. Developers can set fixed font scaling via `SetFontSizeScale(float)`, or enforce boundaries using the `SetMinimumFontSizeScale(float)` and `SetMaximumFontSizeScale(float)`.

System-level scaling can be toggled using the `SetSystemFontSizeScaleEnabled(bool)`, which allows the component to respect global accessibility font settings. Text alignment within the view is managed by the `SetHorizontalTextAlignment(Text::Alignment)` and `SetVerticalTextAlignment(Text::Alignment)`.

Handling overflow scenarios when text exceeds the bounds is managed by the `SetOverflowMode(Text::OverflowMode)`, which supports clipping or ellipsis truncation.

```cpp
InputField inputField = InputField::New();
inputField.SetFontSizeScale(1.2f);
inputField.SetMinimumFontSizeScale(0.8f);
inputField.SetMaximumFontSizeScale(2.0f);
inputField.SetHorizontalTextAlignment(Text::Alignment::CENTER);
inputField.SetOverflowMode(Text::OverflowMode::ELLIPSIS);
```

## Input Handling & Signals

The component communicates changes and limitations to the application through signals. Use the `TextChangedSignal()` to monitor every modification to the content. To restrict the amount of data entered, define a character limit with the `SetMaximumLength(int)`; the component will emit the `MaximumLengthReachedSignal()` when this threshold is triggered.

Cursor-specific interaction can also be tracked using the `CursorPositionChangedSignal()`.

```cpp
class MyHandler
{
public:
  void OnTextChanged(View view) {}
  void OnCursorChanged(View view, uint32_t pos) {}
};

MyHandler* handler = new MyHandler();
InputField inputField = InputField::New();
inputField.TextChangedSignal().Connect(handler, &MyHandler::OnTextChanged);
inputField.CursorPositionChangedSignal().Connect(handler, &MyHandler::OnCursorChanged);
```

## Related Sub-Components

InputFieldImpl provides the necessary internal state management logic for the text input engine. 
→ See: [InputFieldImpl]

InputFieldPropertyHandler simplifies the management and retrieval of dynamic UI property updates for the component. 
→ See: [InputFieldPropertyHandler]
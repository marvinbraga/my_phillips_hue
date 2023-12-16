function loadConfigurations() {
    $.getJSON(`/configurations`, function (data) {
        const configurationsSelect = $('#configurations');
        $.each(data, function (index, item) {
            configurationsSelect.append($('<option>', {
                value: item.name,
                text: `${item.name} - ${item.description.trim().slice(0, 100)}`
            }));
        });
    });
}

function applyConfiguration(event) {
    event.preventDefault();

    const configName = $('#configurations').val();
    const transitionTimeSecs = $('#transition_time_secs').val();
    const durationMinutes = $('#duration_minutes').val();

    $.ajax({
        type: 'POST',
        url: `/apply`,
        contentType: 'application/json',
        data: JSON.stringify({
            config_name: configName,
            transition_time_secs: transitionTimeSecs,
            duration_minutes: durationMinutes
        }),
        success: function (data) {
             alert(`Configuration applied successfully!\n\nDetails:\n- Config Name: ${data.details.config_name}\n- Transition Time (secs): ${data.details.transition_time_secs}\n- Duration (minutes): ${data.details.duration_minutes}`);
        },
        error: function (jqXHR, textStatus, errorThrown) {
            alert('Error applying configuration: ' + errorThrown);
        }
    });
}

$(document).ready(function () {
    loadConfigurations();
    $('#apply-btn').click(applyConfiguration);
});
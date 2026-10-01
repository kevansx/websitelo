let autocomplete;
let address1Field;
let address2Field;
let postalField;

function initAutocomplete(ipCountry) {
	address1Field = document.querySelector("#searchAddressField");
	address2Field = document.querySelector("#registerAddressStreet");
	postalField = document.querySelector("#postcode");
	autocomplete = new google.maps.places.Autocomplete(address1Field, {
		componentRestrictions: { country: ipCountry },
		fields: ["address_components"],
		types: ["address"],
	});
	address1Field.focus();
	autocomplete.addListener("place_changed", fillInAddress);
}

function fillInAddress() {
	$("#registerAddressDetails,.registerConfirmSection").show();
	$(".registerAddressManual").hide();
	
	const place = autocomplete.getPlace();
	let address1 = "";
	let postcode = "";

	for (const component of place.address_components) {
		const componentType = component.types[0];
		switch (componentType) {
			case "street_number":
			address1 += component.long_name+" ";
			break;
			
			case "route":
				address1 += component.long_name;
				document.querySelector("#registerAddressStreet").value = address1;
				break;

			case "postal_code":
				document.querySelector("#registerAddressPostCode").value = component.long_name;
				break;

			case "postal_town":
				$("#registerAddressCity option").filter(function() {
					return $(this).text() == component.long_name;
				}).prop("selected", true);
				break;
			
			case "locality":
				$("#registerAddressCity option").filter(function() {
					let removeAccents = component.long_name.normalize("NFD").replace(/[\u0300-\u036f]/g, "");
					if($(this).text() == removeAccents){
						return $(this).text() == removeAccents;
					}
					return $(this).val() == '';
				}).prop("selected", true);
				break;
			
			case "administrative_area_level_3":
				if($("#registerAddressCity").val() == ''){
					$("#registerAddressCity option").filter(function() {
						let removeAccents = component.long_name.normalize("NFD").replace(/[\u0300-\u036f]/g, "");
						if($(this).text() == removeAccents){
							return $(this).text() == removeAccents;
						}
						return $(this).val() == '';
					}).prop("selected", true);
					break;
				}
		}
	}
	address1Field.value = address1;
	$("#searchAddressField").val('');
	address2Field.focus();
}

window.initAutocomplete = initAutocomplete;